#!/usr/bin/env python3
"""
historical_backfill.py — Import historical TAF/METAR data from Iowa
Environmental Mesonet for all airports already tracked in the database.

Sources:
  TAFs:   https://mesonet.agron.iastate.edu/cgi-bin/request/taf.py
  METARs: https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py

Run from the backend/ directory:
  python historical_backfill.py
  python historical_backfill.py --days 30
  python historical_backfill.py --airports KORD KJFK   # test a subset first
  python historical_backfill.py --start 2025-04-01 --end 2025-05-01
"""

from __future__ import annotations

import argparse
import ast
import csv
import io
import logging
import re
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import get_session, init_db
from fetch import parse_metar_raw, _parse_weather_phenomena
from ingest import _upsert_taf, _upsert_metar, _score_unscored_from_db
from models import Airport

logger = logging.getLogger(__name__)

MESONET_TAF_URL  = "https://mesonet.agron.iastate.edu/cgi-bin/request/taf.py"
MESONET_ASOS_URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"
REQUEST_TIMEOUT  = 120  # seconds

# Semaphore limiting concurrent Mesonet HTTP requests regardless of worker count.
# Keeps network concurrency low to avoid 429s while still parallelising DB writes.
_fetch_sem = threading.Semaphore(3)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    """Parse Mesonet datetime string → aware UTC datetime."""
    if not s or not s.strip():
        return None
    s = s.strip().replace(" ", "T")
    if not s.endswith("Z") and "+" not in s:
        s += "+00:00"
    elif s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _to_iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _parse_bool(v) -> bool:
    """Parse Python-style bool string or int."""
    if isinstance(v, bool):
        return v
    if isinstance(v, int):
        return bool(v)
    s = str(v).strip().lower()
    return s in ("true", "1", "yes")


def _parse_list_field(v) -> list:
    """Parse Mesonet's Python list string (e.g. "['BKN', 'OVC']" or "[]")."""
    if not v or not v.strip():
        return []
    try:
        result = ast.literal_eval(v.strip())
        return result if isinstance(result, list) else []
    except Exception:
        return []


def _int_or_none(v) -> Optional[int]:
    try:
        f = float(v)
        return int(f) if f != 0 or str(v).strip() != "0" else 0
    except (ValueError, TypeError):
        return None


def _float_or_none(v) -> Optional[float]:
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _sky_ceiling(skyc: list[str], skyl_ft: list) -> tuple[Optional[int], Optional[str]]:
    """Return (ceiling_ft, coverage) — lowest BKN/OVC/VV layer."""
    ceil_ft: Optional[int] = None
    ceil_cov: Optional[str] = None
    for cov, hgt in zip(skyc, skyl_ft):
        cov_str = str(cov).upper().strip()
        if cov_str in ("BKN", "OVC", "VV"):
            try:
                h = int(hgt)
                if ceil_ft is None or h < ceil_ft:
                    ceil_ft = h
                    ceil_cov = cov_str
            except (ValueError, TypeError):
                pass
    return ceil_ft, ceil_cov


def _sky_string(skyc: list, skyl_ft: list) -> Optional[str]:
    parts = []
    for cov, hgt in zip(skyc, skyl_ft):
        cov_str = str(cov).upper().strip()
        if not cov_str:
            continue
        if cov_str in ("CLR", "SKC", "NSC", "CAVOK"):
            parts.append(cov_str)
        else:
            try:
                h = int(hgt)
                parts.append(f"{cov_str}{h // 100:03d}")
            except (ValueError, TypeError):
                parts.append(cov_str)
    return " ".join(parts) if parts else None


# ---------------------------------------------------------------------------
# Iowa Mesonet TAF fetch
# ---------------------------------------------------------------------------

def _fetch_csv(url: str, params: dict) -> Optional[str]:
    """Fetch CSV text from a Mesonet endpoint with retry/backoff on 429."""
    for attempt in range(5):
        try:
            with _fetch_sem:
                with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
                    resp = client.get(url, params=params)
            if resp.status_code == 429:
                wait = 10 * (attempt + 1)
                logger.warning("429 from Mesonet (attempt %d), waiting %ds", attempt + 1, wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            content = resp.text.strip()
            if not content or content.startswith("ERROR") or "No Data" in content[:200]:
                return None
            return content
        except httpx.HTTPStatusError:
            raise
        except Exception as exc:
            logger.warning("Fetch error %s %s: %s", url, params.get("station", ""), exc)
            return None
    return None


def fetch_mesonet_tafs(icao: str, start_dt: datetime, end_dt: datetime) -> list[dict]:
    """
    Fetch TAF data from Iowa Mesonet taf.py for one station.
    Returns a list of TAF dicts compatible with ingest._upsert_taf().
    """
    params = {
        "station": icao.upper(),
        "sts":     start_dt.strftime("%Y-%m-%dT%H:%MZ"),
        "ets":     end_dt.strftime("%Y-%m-%dT%H:%MZ"),
    }
    content = _fetch_csv(MESONET_TAF_URL, params)
    if not content:
        return []

    reader = csv.DictReader(io.StringIO(content))
    rows = list(reader)
    if not rows:
        return []

    # Group rows by product_id (each = one TAF bulletin)
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        pid = row.get("product_id", "").strip()
        if not pid:
            pid = f"{row.get('station', '')}_{row.get('valid', '')}"
        groups[pid].append(row)

    tafs: list[dict] = []
    for product_id, group_rows in groups.items():
        taf = _build_taf_dict(icao, group_rows)
        if taf:
            tafs.append(taf)

    tafs.sort(key=lambda t: t.get("issue_time") or "")
    return tafs


def _build_taf_dict(icao: str, rows: list[dict]) -> Optional[dict]:
    """Construct one TAF dict from all rows sharing a product_id."""
    if not rows:
        return None

    # Sort: Observation row first, then Forecasts by fx_valid
    def _sort_key(r):
        ftype = r.get("ftype", "")
        fx = r.get("fx_valid", r.get("valid", ""))
        return (0 if "Observation" in ftype else 1, fx)

    rows = sorted(rows, key=_sort_key)
    first = rows[0]

    # Issue time (valid = TAF bulletin issue time, same for all rows in group)
    issue_dt = _parse_dt(first.get("valid"))
    if not issue_dt:
        return None

    # Amendment flag
    is_amendment = _parse_bool(first.get("is_amendment", False))

    # Separate background periods (FM/BASE) from conditional (TEMPO/PROB)
    obs_rows      = [r for r in rows if "Observation" in r.get("ftype", "")]
    fc_rows       = [r for r in rows if "Observation" not in r.get("ftype", "")]
    fc_sorted     = sorted(fc_rows, key=lambda r: r.get("fx_valid", ""))

    # Collect all period dicts
    periods: list[dict] = []
    seq = 0

    # ── Observation row → BASE period ────────────────────────────────────────
    if obs_rows:
        obs = obs_rows[0]
        obs_from = _parse_dt(obs.get("fx_valid") or obs.get("valid"))
        # BASE period ends at the first FM forecast row (or issue+30h if none)
        first_fc_start = _parse_dt(fc_sorted[0].get("fx_valid")) if fc_sorted else None
        obs_to = first_fc_start or (issue_dt + timedelta(hours=30))

        if obs_from:
            p = _build_period_dict(obs, seq, "BASE", obs_from, obs_to)
            if p:
                periods.append(p)
                seq += 1

    # ── Forecast rows: infer FM end times; TEMPO/PROB have explicit ends ──────
    # Collect FM milestones for end-time inference
    fm_starts = sorted(
        [_parse_dt(r.get("fx_valid")) for r in fc_sorted
         if _infer_period_type(r) not in ("TEMPO", "PROB")
         and _parse_dt(r.get("fx_valid"))],
        key=lambda x: x
    )

    for i, row in enumerate(fc_sorted):
        ftype = row.get("ftype", "")
        period_type = _infer_period_type(row)

        fx_from = _parse_dt(row.get("fx_valid"))
        if not fx_from:
            continue

        # TEMPO/PROB have explicit fx_valid_end; FM rows need inference
        fx_to_raw = _parse_dt(row.get("fx_valid_end") or "")
        if fx_to_raw:
            fx_to = fx_to_raw
        elif period_type in ("FM", "BECMG", "BASE"):
            # End at the next FM/BECMG milestone, or issue + 30h
            next_start = next(
                (t for t in fm_starts if t > fx_from), None
            )
            fx_to = next_start if next_start else issue_dt + timedelta(hours=30)
        else:
            # Should have an explicit end but doesn't — skip
            continue

        p = _build_period_dict(row, seq, period_type, fx_from, fx_to)
        if p:
            periods.append(p)
            seq += 1

    if not periods:
        return None

    # Overall TAF valid window
    all_froms = [_parse_dt(p["valid_from"]) for p in periods if p.get("valid_from")]
    all_tos   = [_parse_dt(p["valid_to"])   for p in periods if p.get("valid_to")]
    taf_from  = min(all_froms) if all_froms else issue_dt
    taf_to    = max(all_tos)   if all_tos   else issue_dt + timedelta(hours=30)

    # Pseudo raw_text from period fragments
    frag_parts = [r.get("raw", "") for r in rows if r.get("raw")]
    raw_hdr = (
        f"TAF {'AMD ' if is_amendment else ''}{icao.upper()} "
        f"{issue_dt.strftime('%d%H%MZ')} "
        f"{taf_from.strftime('%d%H')}/{taf_to.strftime('%d%H')}"
    )
    raw_text = raw_hdr + " " + " ".join(frag_parts)

    return {
        "icao":          icao.upper(),
        "issue_time":    _to_iso(issue_dt),
        "valid_from":    _to_iso(taf_from),
        "valid_to":      _to_iso(taf_to),
        "raw_text":      raw_text,
        "is_amendment":  is_amendment,
        "is_correction": False,
        "periods":       periods,
    }


def _infer_period_type(row: dict) -> str:
    """Determine TAF period type from ftype and raw fragment."""
    ftype   = row.get("ftype", "")
    raw     = (row.get("raw", "") or "").upper()
    is_tempo = _parse_bool(row.get("is_tempo", False))

    if "Probability" in ftype or "Prob" in ftype:
        return "PROB"
    if is_tempo or "TEMPO" in ftype or raw.startswith("TEMPO"):
        return "TEMPO"
    if "BECMG" in raw or "BECMG" in ftype:
        return "BECMG"
    # Default FM for forecast rows; caller handles Observation → BASE
    return "FM"


def _build_period_dict(
    row: dict,
    seq: int,
    period_type: str,
    valid_from: datetime,
    valid_to: datetime,
) -> Optional[dict]:
    """Build a single TAFPeriod dict from a Mesonet TAF row."""
    # ── Wind ────────────────────────────────────────────────────────────────
    raw_frag  = (row.get("raw", "") or "").upper()
    drct_raw  = _float_or_none(row.get("drct"))
    sknt_raw  = _float_or_none(row.get("sknt"))
    gust_raw  = _float_or_none(row.get("gust"))

    drct  = int(drct_raw) if drct_raw is not None else None
    sknt  = int(sknt_raw) if sknt_raw is not None else None
    gust  = int(gust_raw) if gust_raw is not None and gust_raw > 0 else None

    # VRB wind: drct=0 with speed>0, or "VRB" in raw fragment
    wind_variable = "VRB" in raw_frag or (drct == 0 and sknt is not None and sknt > 0)
    wind_dir = None if wind_variable else drct

    # ── Visibility ──────────────────────────────────────────────────────────
    vis = _float_or_none(row.get("visibility"))
    visibility_gt = vis is not None and (vis >= 6.0 or "P6SM" in raw_frag)

    # ── Sky layers (stored as Python list strings) ────────────────────────
    skyc_list = _parse_list_field(row.get("skyc", "[]"))
    skyl_list = _parse_list_field(row.get("skyl", "[]"))

    ceil_ft, ceil_cov = _sky_ceiling(skyc_list, skyl_list)
    sky_str = _sky_string(skyc_list, skyl_list)

    # ── Weather phenomena (stored as Python list string) ─────────────────
    wx_raw = _parse_list_field(row.get("presentwx", "[]"))
    # wx_raw is already a list like ['-TSRA', 'FG']
    # Run through our normalizer for consistency
    wx_str = " ".join(str(w) for w in wx_raw)
    wx = _parse_weather_phenomena(wx_str) if wx_str.strip() else []

    # ── Probability ─────────────────────────────────────────────────────────
    probability: Optional[int] = None
    if period_type == "PROB":
        ftype = row.get("ftype", "")
        m = re.search(r"(\d{2})", ftype)
        if not m:
            m = re.search(r"PROB(\d{2})", raw_frag)
        if m:
            probability = int(m.group(1))

    return {
        "period_type":       period_type,
        "period_seq":        seq,
        "valid_from":        _to_iso(valid_from),
        "valid_to":          _to_iso(valid_to),
        "wind_dir":          wind_dir,
        "wind_variable":     wind_variable,
        "wind_speed":        sknt,
        "wind_gust":         gust,
        "visibility_sm":     vis,
        "visibility_gt":     visibility_gt,
        "ceiling_ft":        ceil_ft,
        "ceiling_coverage":  ceil_cov,
        "sky_string":        sky_str,
        "weather_phenomena": wx,
        "probability":       probability,
    }


# ---------------------------------------------------------------------------
# Iowa Mesonet METAR fetch
# ---------------------------------------------------------------------------

def fetch_mesonet_metars(icao: str, start_dt: datetime, end_dt: datetime) -> list[dict]:
    """
    Fetch METAR observations from Iowa Mesonet ASOS archive.
    Uses raw METAR text and parses with the existing parse_metar_raw() for consistency.
    """
    params = {
        "station": icao.upper(),
        "data":    "metar",
        "sts":     start_dt.strftime("%Y-%m-%dT%H:%MZ"),
        "ets":     end_dt.strftime("%Y-%m-%dT%H:%MZ"),
        "tz":      "UTC",
    }
    content = _fetch_csv(MESONET_ASOS_URL, params)
    if not content:
        return []

    reader = csv.DictReader(io.StringIO(content))
    results: list[dict] = []

    for row in reader:
        raw = (row.get("metar") or "").strip()
        if not raw or raw.lower() in ("none", "null", "m", "missing"):
            continue
        try:
            parsed = parse_metar_raw(raw)
        except Exception as exc:
            logger.debug("%s: METAR parse failed %r: %s", icao, raw[:60], exc)
            continue

        parsed["raw_text"]     = raw
        parsed["airport_icao"] = icao.upper()
        results.append(parsed)

    results.sort(key=lambda r: r.get("observation_time") or "")
    return results


# ---------------------------------------------------------------------------
# Per-station backfill
# ---------------------------------------------------------------------------

def backfill_station(icao: str, start_dt: datetime, end_dt: datetime) -> dict:
    stats = dict(
        icao=icao, tafs_new=0, tafs_seen=0,
        metars_new=0, metars_seen=0, scores_new=0, errors=[]
    )

    tafs   = fetch_mesonet_tafs(icao, start_dt, end_dt)
    metars = fetch_mesonet_metars(icao, start_dt, end_dt)

    with get_session() as session:
        # Ensure airport stub exists (should already be there from live ingest)
        if not session.get(Airport, icao.upper()):
            session.add(Airport(icao=icao.upper(), name=icao.upper()))
            session.flush()

        for taf_data in tafs:
            try:
                with session.begin_nested():
                    _, new = _upsert_taf(session, taf_data)
                stats["tafs_new" if new else "tafs_seen"] += 1
            except Exception as exc:
                stats["errors"].append(f"TAF write: {exc}")
                logger.debug("%s TAF write error: %s", icao, exc)

        for metar_data in metars:
            try:
                with session.begin_nested():
                    _, new = _upsert_metar(session, metar_data)
                stats["metars_new" if new else "metars_seen"] += 1
            except Exception as exc:
                stats["errors"].append(f"METAR write: {exc}")
                logger.debug("%s METAR write error: %s", icao, exc)

    try:
        stats["scores_new"] = _score_unscored_from_db(icao)
    except Exception as exc:
        stats["errors"].append(f"Scoring: {exc}")
        logger.warning("%s scoring error: %s", icao, exc)

    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Historical TAF/METAR backfill from Iowa Environmental Mesonet",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--days",     type=int, default=30,
                        help="Days of history to fetch (default: 30)")
    parser.add_argument("--start",    metavar="YYYY-MM-DD",
                        help="Explicit start date (overrides --days)")
    parser.add_argument("--end",      metavar="YYYY-MM-DD",
                        help="Explicit end date (default: now)")
    parser.add_argument("--airports", nargs="+", metavar="ICAO",
                        help="Specific airports (default: all in DB)")
    parser.add_argument("--workers",  type=int, default=4,
                        help="Parallel worker threads (default: 4)")
    parser.add_argument("--verbose",  "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        stream=sys.stderr,
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)-8s %(message)s",
        datefmt="%H:%M:%S",
    )

    now = datetime.now(timezone.utc)
    end_dt = (
        datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)
        if args.end else now
    )
    start_dt = (
        datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
        if args.start else end_dt - timedelta(days=args.days)
    )

    print(f"Date range : {start_dt.date()} → {end_dt.date()}")
    init_db()

    if args.airports:
        stations = [s.upper() for s in args.airports]
    else:
        with get_session() as session:
            stations = [row[0] for row in session.query(Airport.icao).all()]

    total = len(stations)
    print(f"Stations   : {total}")
    print(f"Workers    : {args.workers} (network semaphore: 3)\n")

    t_start = time.monotonic()
    done = failed = 0
    sum_tafs = sum_metars = sum_scores = 0
    width = len(str(total))
    print_lock = threading.Lock()

    def process(icao):
        return icao, backfill_station(icao, start_dt, end_dt)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(process, icao): icao for icao in stations}
        for future in as_completed(futures):
            icao, stats = future.result()
            with print_lock:
                done += 1
                if stats["errors"]:
                    failed += 1
                sum_tafs   += stats["tafs_new"]
                sum_metars += stats["metars_new"]
                sum_scores += stats["scores_new"]
                line = (
                    f"[{done:>{width}}/{total}] {icao}"
                    f"  TAFs +{stats['tafs_new']}/{stats['tafs_new']+stats['tafs_seen']}"
                    f"  METARs +{stats['metars_new']}/{stats['metars_new']+stats['metars_seen']}"
                    f"  scores +{stats['scores_new']}"
                )
                if stats["errors"]:
                    line += f"  ⚠ {len(stats['errors'])} err ({stats['errors'][0][:60]})"
                print(line)

    elapsed = time.monotonic() - t_start
    print(
        f"\nFinished in {elapsed:.0f}s — "
        f"{total-failed}/{total} OK, {failed} with errors\n"
        f"Total: TAFs +{sum_tafs}  METARs +{sum_metars}  Scores +{sum_scores}"
    )
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
