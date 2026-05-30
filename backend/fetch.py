"""
fetch.py — Retrieve and parse TAFs and METARs from aviationweather.gov.

Public API
----------
  fetch_metars(icao, hours)  → list[dict]   decoded METAR records
  fetch_tafs(icao)           → list[dict]   decoded TAF records (with periods)
  parse_metar_raw(raw)       → dict         single METAR decoded fields
  parse_taf_raw(raw, ref_dt) → dict         TAF header + list[period dicts]

Design notes
------------
* The aviationweather.gov ADDS API requires no authentication.
* We request JSON format from the API for envelope metadata (station info,
  issue times) and also retrieve the raw text so we can parse details that
  the API may omit (sky layers, all TEMPO/PROB groups, etc.).
* METAR decoding uses the ``metar`` PyPI library for reliability.
* TAF parsing is hand-rolled; third-party libraries handle TAF poorly,
  especially BECMG/TEMPO/PROB sequencing and date rollover edge cases.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from metar import Metar as MetarLib

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_URL = "https://aviationweather.gov/api/data"
REQUEST_TIMEOUT = 30  # seconds

# Weather phenomenon tokens we track for scoring.
# These are the base codes (without intensity prefix or descriptor suffix).
TRACKED_PHENOMENA = {
    "TS",   # thunderstorm
    "RA",   # rain
    "SN",   # snow
    "DZ",   # drizzle
    "FG",   # fog
    "BR",   # mist
    "GR",   # hail
    "GS",   # small hail / snow pellets
    "IC",   # ice crystals
    "PL",   # ice pellets
    "SQ",   # squall
    "FC",   # funnel cloud / tornado
    "FZRA", # freezing rain (descriptor+precip combined)
    "FZDZ", # freezing drizzle
    "BLSN", # blowing snow
    "HZ",   # haze
    "VA",   # volcanic ash
}

# Regex patterns compiled once at import time.
_WIND_RE     = re.compile(
    r'\b(?P<dir>\d{3}|VRB)(?P<spd>\d{2,3})(?:G(?P<gust>\d{2,3}))?KT\b'
)
# Visibility (US statute miles).  Handles: P6SM, 6SM, 1/2SM, 1 1/2SM, 3/4SM.
# Structure: optional "P" (greater-than) prefix, then either:
#   • whole number optionally followed by a space + fraction  (6SM, 1 1/2SM)
#   • standalone fraction                                     (1/2SM)
_VIS_SM_RE   = re.compile(
    r'\b(?P<gt>P)?'
    r'(?:(?P<whole>\d+)(?:\s+(?P<num>\d+)/(?P<den>\d+))?'
    r'|(?P<num2>\d+)/(?P<den2>\d+))'
    r'SM\b'
)
# Sky: FEW040, SCT025CB, BKN012, OVC008, VV010, SKC, CLR, NSC, CAVOK
_SKY_RE      = re.compile(
    r'\b(?P<cov>SKC|CLR|NSC|CAVOK|FEW|SCT|BKN|OVC|VV)'
    r'(?P<hgt>\d{3})?(?:CB|TCU)?\b'
)
# FM time:  FM251500  (day=25 hour=15 min=00)
_FM_TIME_RE  = re.compile(r'\bFM(\d{2})(\d{2})(\d{2})\b')
# Period time range:  2512/2618  (day=25 hr=12 → day=26 hr=18)
_PERIOD_RE   = re.compile(r'\b(\d{2})(\d{2})/(\d{2})(\d{2})\b')
# TAF header issue time:  251130Z
_ISSUE_RE    = re.compile(r'\b(\d{2})(\d{2})(\d{2})Z\b')


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _get(url: str, params: dict, retries: int = 4) -> list[dict]:
    """
    GET request with exponential-backoff retry.

    Retries on HTTP 429 (rate-limit) and 5xx errors, as well as transient
    network failures.  Raises on the final attempt if still failing.
    """
    import time as _time

    for attempt in range(retries):
        try:
            with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
                resp = client.get(url, params=params)

            if resp.status_code == 429 or resp.status_code >= 500:
                wait = 2 ** attempt          # 1 s, 2 s, 4 s, 8 s
                logger.warning(
                    "HTTP %s from %s (attempt %d/%d) — retrying in %ds",
                    resp.status_code, url, attempt + 1, retries, wait,
                )
                _time.sleep(wait)
                continue

            resp.raise_for_status()
            if not resp.content or not resp.content.strip():
                return []   # API returns empty body when no data for station
            data = resp.json()
            if isinstance(data, list):
                return data
            raise RuntimeError(f"Unexpected API response: {data}")

        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            wait = 2 ** attempt
            logger.warning(
                "Network error (attempt %d/%d): %s — retrying in %ds",
                attempt + 1, retries, exc, wait,
            )
            if attempt + 1 == retries:
                raise
            _time.sleep(wait)

    # Final attempt exhausted by status-code loop
    resp.raise_for_status()
    raise RuntimeError("Retry loop exhausted")


# ---------------------------------------------------------------------------
# Date / time utilities
# ---------------------------------------------------------------------------

def _make_utc(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def _resolve_ddhh(dd: int, hh: int, ref_dt: datetime) -> datetime:
    """
    Convert a DDHH day-of-month + hour pair to a full UTC datetime.

    TAF times are always UTC and use the current month as implicit context.
    When ``dd`` is less than the reference day we've crossed a month boundary
    (e.g. TAF issued on the 30th, valid until the 2nd of next month).

    ICAO convention allows hh=24 to mean "end of the day" (equivalent to
    00:00 of the following day).  We handle this by resolving the base date
    with hh=0 and adding one day.
    """
    # hh=24 means midnight end-of-day: resolve as next-day 00:00
    if hh == 24:
        base = _resolve_ddhh(dd, 0, ref_dt)
        return base + timedelta(days=1)

    # Try current month first
    try:
        candidate = _make_utc(ref_dt.year, ref_dt.month, dd, hh)
    except ValueError:
        candidate = None

    if candidate is None or dd < ref_dt.day - 7:
        # Roll forward one month
        if ref_dt.month == 12:
            candidate = _make_utc(ref_dt.year + 1, 1, dd, hh)
        else:
            candidate = _make_utc(ref_dt.year, ref_dt.month + 1, dd, hh)

    return candidate


def _resolve_ddhhMM(dd: int, hh: int, mm: int, ref_dt: datetime) -> datetime:
    """Same as _resolve_ddhh but also includes minutes (for FM groups)."""
    base = _resolve_ddhh(dd, hh, ref_dt)
    return base.replace(minute=mm)


# ---------------------------------------------------------------------------
# Condition string parsers (shared by METAR + TAF)
# ---------------------------------------------------------------------------

def _parse_wind(token_str: str) -> dict:
    """
    Extract wind components from a string that may contain a wind token.

    Returns dict with keys: wind_dir (int|None), wind_variable (bool),
    wind_speed (int|None), wind_gust (int|None).
    """
    m = _WIND_RE.search(token_str)
    if not m:
        return {"wind_dir": None, "wind_variable": False,
                "wind_speed": None, "wind_gust": None}
    d = m.group("dir")
    return {
        "wind_dir":      None if d == "VRB" else int(d),
        "wind_variable": d == "VRB",
        "wind_speed":    int(m.group("spd")),
        "wind_gust":     int(m.group("gust")) if m.group("gust") else None,
    }


def _parse_visibility_sm(token_str: str) -> tuple[Optional[float], bool]:
    """
    Parse a US-format visibility string (SM units).

    Returns (value_sm, is_greater_than).
    Examples:
      "P6SM"    → (6.0,  True)   greater-than prefix
      "6SM"     → (6.0,  False)
      "1/2SM"   → (0.5,  False)  standalone fraction
      "1 1/2SM" → (1.5,  False)  whole + fraction
      "3SM"     → (3.0,  False)
    Returns (None, False) if no SM token found.
    """
    m = _VIS_SM_RE.search(token_str)
    if not m:
        return None, False

    gt    = bool(m.group("gt"))
    whole = int(m.group("whole"))  if m.group("whole") else 0
    # Fraction may come from the "whole + fraction" branch or standalone branch
    num   = int(m.group("num"))    if m.group("num")   else (
            int(m.group("num2"))   if m.group("num2")  else 0)
    den   = int(m.group("den"))    if m.group("den")   else (
            int(m.group("den2"))   if m.group("den2")  else 1)

    value = whole + (num / den if num else 0)
    if value == 0 and not gt:
        return None, False  # bare "SM" with no number — skip
    return float(value), gt


def _parse_sky_layers(token_str: str) -> tuple[Optional[int], Optional[str], str]:
    """
    Find all sky-cover tokens in ``token_str`` and derive the ceiling.

    Ceiling = lowest BKN, OVC, or VV layer in hundreds of feet AGL.
    FEW and SCT layers do not constitute a ceiling.

    Returns (ceiling_ft, ceiling_coverage, raw_sky_string).
      ceiling_coverage  The coverage type of the lowest ceiling layer
                        ("BKN", "OVC", or "VV"), or None when no ceiling.
    """
    layers = _SKY_RE.findall(token_str)
    ceiling_ft: Optional[int] = None
    ceiling_coverage: Optional[str] = None
    sky_parts: list[str] = []

    for cov, hgt in layers:
        if cov in ("SKC", "CLR", "NSC", "CAVOK"):
            sky_parts.append(cov)
            continue  # no ceiling
        if hgt:
            altitude_ft = int(hgt) * 100
            sky_parts.append(f"{cov}{hgt}")
            if cov in ("BKN", "OVC", "VV"):
                if ceiling_ft is None or altitude_ft < ceiling_ft:
                    ceiling_ft = altitude_ft
                    ceiling_coverage = cov
        else:
            sky_parts.append(cov)

    return ceiling_ft, ceiling_coverage, " ".join(sky_parts)


# Weather phenomena token regex.  Matches intensity prefix + descriptor +
# phenomenon body, e.g. "-RASN", "+TSRA", "FZRA", "FG", "BR".
_WX_TOKEN_RE = re.compile(
    r'(?P<int>[-+]|VC)?'
    r'(?P<desc>MI|PR|BC|DR|BL|SH|TS|FZ)?'
    r'(?P<phen>DZ|RA|SN|SG|IC|PL|GR|GS|UP|FG|VA|BR|HZ|DU|SA|PY|SQ|FC|SS|DS|TS)\b'
)

# Tokens that look like weather but are actually other TAF/METAR keywords
_NON_WX_WORDS = {
    "BECMG", "TEMPO", "FM", "PROB", "TAF", "AMD", "COR",
    "SKC", "CLR", "FEW", "SCT", "BKN", "OVC", "VV", "NSC", "CAVOK",
    "KT", "SM", "RMK", "SLP", "QNH", "NOSIG",
}


def _parse_weather_phenomena(token_str: str) -> list[str]:
    """
    Extract weather-phenomenon tokens from a condition string.

    Returns a list of canonical strings like ["-RA", "FG", "+TSRA"].
    Duplicate entries are removed; order is preserved.

    The function is conservative: tokens that match aviation-keyword patterns
    but are not valid weather codes are filtered out.
    """
    # Split into whitespace-delimited tokens for validation context
    raw_tokens = token_str.upper().split()
    results: list[str] = []
    seen: set[str] = set()

    for tok in raw_tokens:
        if tok in _NON_WX_WORDS:
            continue
        # Must start with an optional intensity/descriptor then a phenomenon
        for m in _WX_TOKEN_RE.finditer(tok):
            intensity = m.group("int")  or ""
            desc      = m.group("desc") or ""
            phen      = m.group("phen")

            # Build canonical token (e.g. "-RA", "FZRA", "+TSRA")
            canonical = f"{intensity}{desc}{phen}"

            # Construct the base phenomenon key for TRACKED_PHENOMENA lookup
            # "FZRA" → "FZRA", "BLSN" → "BLSN", plain "RA" → "RA"
            base_key = f"{desc}{phen}" if desc else phen

            if base_key not in TRACKED_PHENOMENA:
                # Fall back to just the phenomenon code
                if phen not in TRACKED_PHENOMENA:
                    continue

            if canonical not in seen:
                seen.add(canonical)
                results.append(canonical)

    return results


# ---------------------------------------------------------------------------
# METAR parsing  (wraps the ``metar`` library)
# ---------------------------------------------------------------------------

def parse_metar_raw(raw: str) -> dict:
    """
    Decode a raw METAR string into a structured dict.

    Uses the ``metar`` PyPI library for the heavy lifting, then normalises
    units and extracts the ceiling.  Falls back to regex extraction for fields
    the library omits.

    Returns
    -------
    dict with keys:
        observation_time  str  ISO-8601 UTC
        wind_dir          int | None
        wind_variable     bool
        wind_speed        int | None   (knots)
        wind_gust         int | None   (knots)
        visibility_sm     float | None
        ceiling_ft        int | None
        weather_phenomena list[str]
        flight_category   str          VFR | MVFR | IFR | LIFR
    """
    try:
        obs = MetarLib.Metar(raw, strict=False)
    except Exception as exc:
        logger.warning("metar library parse failed for %r: %s", raw[:60], exc)
        raise

    # --- Observation time ---
    obs_time = obs.time  # datetime (UTC) or None
    obs_time_iso = obs_time.isoformat() if obs_time else None

    # --- Wind ---
    try:
        wspd = int(obs.wind_speed.value("KT")) if obs.wind_speed else None
    except Exception:
        wspd = None
    try:
        wdir = int(obs.wind_dir.value()) if obs.wind_dir else None
    except Exception:
        wdir = None
    try:
        wgust = int(obs.wind_gust.value("KT")) if obs.wind_gust else None
    except Exception:
        wgust = None

    # VRB detection: the metar library sets wind_dir=None for variable winds.
    # Calm wind (00000KT) also has wind_dir=None but speed=0, so we
    # distinguish by checking speed > 0.  Do NOT access wind_dir_variable —
    # it does not exist in metar ≥1.9.
    wind_variable = (
        obs.wind_dir is None
        and obs.wind_speed is not None
        and wspd is not None
        and wspd > 0
    )

    # --- Visibility ---
    try:
        vis_sm = obs.vis.value("SM") if obs.vis else None
    except Exception:
        vis_sm = None

    # --- Sky / Ceiling ---
    ceiling_ft: Optional[int] = None
    ceiling_coverage: Optional[str] = None
    for coverage, altitude, _ in (obs.sky or []):
        if coverage in ("BKN", "OVC", "VV") and altitude:
            try:
                alt_ft = int(altitude.value("FT"))
                if ceiling_ft is None or alt_ft < ceiling_ft:
                    ceiling_ft = alt_ft
                    ceiling_coverage = coverage
            except Exception:
                pass

    # --- Weather phenomena ---
    # The metar library exposes obs.weather as list of tuples; we rebuild
    # the raw token strings and run through our normaliser for consistency.
    wx_tokens: list[str] = []
    for w in (obs.weather or []):
        # metar library returns 5-tuples: (intensity, descriptor, phenomenon, qualifier, extra)
        # Unpack defensively so we tolerate any library version.
        intensity  = (w[0] if len(w) > 0 else "") or ""
        descriptor = (w[1] if len(w) > 1 else "") or ""
        phenomenon = (w[2] if len(w) > 2 else "") or ""
        qualifier  = (w[3] if len(w) > 3 else "") or ""
        tok = f"{intensity}{descriptor}{phenomenon}{qualifier}".strip()
        if tok:
            wx_tokens.append(tok)
    # Supplement with regex pass over the raw string (catches tokens the
    # library may drop, e.g. FZRA in some formats)
    extra_wx = _parse_weather_phenomena(raw)
    # Merge, preserving library order first
    wx_set = set(wx_tokens)
    for e in extra_wx:
        if e not in wx_set:
            wx_tokens.append(e)
            wx_set.add(e)

    # --- Flight category ---
    fc = _flight_category(ceiling_ft, vis_sm)

    return {
        "observation_time":  obs_time_iso,
        "wind_dir":          wdir,
        "wind_variable":     wind_variable,
        "wind_speed":        wspd,
        "wind_gust":         wgust,
        "visibility_sm":     vis_sm,
        "ceiling_ft":        ceiling_ft,
        "ceiling_coverage":  ceiling_coverage,
        "weather_phenomena": wx_tokens,
        "flight_category":   fc,
    }


# ---------------------------------------------------------------------------
# TAF parsing  (custom implementation)
# ---------------------------------------------------------------------------

# Pattern that starts a new period group in a TAF
_GROUP_START_RE = re.compile(
    r'\b(FM\d{6}|BECMG|TEMPO|PROB\d{2}(?:\s+TEMPO)?)\b'
)


def parse_taf_raw(raw: str, ref_dt: Optional[datetime] = None) -> dict:
    """
    Parse a raw TAF bulletin into structured data.

    Parameters
    ----------
    raw    The complete raw TAF string (may include "TAF AMD ICAO …" header).
    ref_dt UTC datetime to use as the month/year anchor for DDHH resolution.
           Defaults to now.  Pass the TAF's bulletin time if known.

    Returns
    -------
    dict with keys:
        icao          str
        issue_time    str   ISO-8601
        valid_from    str   ISO-8601
        valid_to      str   ISO-8601
        raw_text      str
        periods       list[dict]   see _parse_period() for keys
    """
    if ref_dt is None:
        ref_dt = datetime.now(timezone.utc)

    # Normalise whitespace; TAFs from ADDS sometimes have embedded newlines
    text = " ".join(raw.split())

    # --- Extract ICAO and amendment/correction flags ---
    # TAF [AMD|COR|RTD] ICAO DDHHMMZ ...
    header_m = re.match(
        r'^TAF(?:\s+(?:AMD|COR|RTD))*\s+([A-Z]{4})\s+', text
    )
    if not header_m:
        raise ValueError(f"Cannot find ICAO in TAF: {text[:80]}")
    icao         = header_m.group(1)
    header_upper = text[:header_m.end()].upper()
    is_amendment = "AMD" in header_upper
    is_correction = "COR" in header_upper

    # --- Extract issue time (DDHHMMZ) ---
    issue_m = _ISSUE_RE.search(text, header_m.end())
    if not issue_m:
        raise ValueError(f"Cannot find issue time in TAF: {text[:80]}")
    issue_dd, issue_hh, issue_mm = int(issue_m.group(1)), int(issue_m.group(2)), int(issue_m.group(3))
    issue_dt = _resolve_ddhhMM(issue_dd, issue_hh, issue_mm, ref_dt)
    issue_iso = issue_dt.isoformat()

    # --- Extract valid period (DDHH/DDHH) ---
    # First DDHH/DDHH after the issue time
    valid_m = _PERIOD_RE.search(text, issue_m.end())
    if not valid_m:
        raise ValueError(f"Cannot find valid period in TAF: {text[:80]}")
    vf_dd, vf_hh = int(valid_m.group(1)), int(valid_m.group(2))
    vt_dd, vt_hh = int(valid_m.group(3)), int(valid_m.group(4))
    valid_from = _resolve_ddhh(vf_dd, vf_hh, issue_dt)
    valid_to   = _resolve_ddhh(vt_dd, vt_hh, issue_dt)
    # valid_to might be < valid_from if it crosses midnight of the next day
    if valid_to <= valid_from:
        valid_to += timedelta(days=1)

    # --- Split TAF body into groups ---
    # Everything from the end of the valid-period token to the end of the
    # bulletin is the "body".  We split it on group-start markers.
    body_start = valid_m.end()
    body = text[body_start:]

    # Find all group markers and their positions
    markers: list[tuple[int, str]] = []  # (start_pos_in_body, marker_text)
    for m in _GROUP_START_RE.finditer(body):
        markers.append((m.start(), m.group(0)))

    # Slice body into chunks: BASE chunk first, then one chunk per marker
    chunks: list[tuple[str, str]] = []  # (group_type_label, condition_text)

    base_end = markers[0][0] if markers else len(body)
    base_chunk = body[:base_end].strip()
    chunks.append(("BASE", base_chunk))

    for i, (pos, label) in enumerate(markers):
        end = markers[i + 1][0] if i + 1 < len(markers) else len(body)
        chunk_text = body[pos:end].strip()
        chunks.append((label, chunk_text))

    # --- Parse each chunk into a period dict ---
    periods: list[dict] = []
    for seq, (label, chunk) in enumerate(chunks):
        try:
            period = _parse_taf_group(
                label, chunk, seq, valid_from, valid_to, issue_dt
            )
            periods.append(period)
        except Exception as exc:
            logger.warning("Skipping TAF group %r at seq %d: %s", label, seq, exc)

    return {
        "icao":          icao,
        "issue_time":    issue_iso,
        "valid_from":    valid_from.isoformat(),
        "valid_to":      valid_to.isoformat(),
        "raw_text":      raw,
        "is_amendment":  is_amendment,
        "is_correction": is_correction,
        "periods":       periods,
    }


def _parse_taf_group(
    label: str,
    chunk: str,
    seq: int,
    taf_valid_from: datetime,
    taf_valid_to: datetime,
    ref_dt: datetime,
) -> dict:
    """
    Parse a single TAF period group (BASE, FM, BECMG, TEMPO, PROB …).

    Parameters
    ----------
    label           The group marker string, e.g. "FM251500", "BECMG", "PROB30 TEMPO".
    chunk           The full text of this group (includes the label).
    seq             Sequential index within the parent TAF.
    taf_valid_from  Start of the TAF's overall valid period.
    taf_valid_to    End of the TAF's overall valid period.
    ref_dt          Reference datetime for month resolution.

    Returns
    -------
    dict with keys matching TAFPeriod columns.
    """
    upper = chunk.upper()

    # --- Determine period type and valid time bounds ---
    probability: Optional[int] = None

    if label == "BASE":
        period_type = "BASE"
        period_from = taf_valid_from
        period_to   = taf_valid_to  # will be narrowed by first FM group later

    elif label.startswith("FM"):
        period_type = "FM"
        # FM251500 — embedded in the label
        fm_m = _FM_TIME_RE.match(label)
        if not fm_m:
            raise ValueError(f"Bad FM label: {label!r}")
        period_from = _resolve_ddhhMM(
            int(fm_m.group(1)), int(fm_m.group(2)), int(fm_m.group(3)), ref_dt
        )
        period_to = taf_valid_to  # FM lasts until end of TAF (or next FM)

    else:
        # BECMG / TEMPO / PROB30 / PROB40 / PROB40 TEMPO
        if "PROB" in upper:
            prob_m = re.search(r'PROB(\d{2})', upper)
            probability = int(prob_m.group(1)) if prob_m else None
            period_type = "PROB"
            if "TEMPO" in upper:
                period_type = "PROB"  # store as PROB; tempo_active flag set at score time
        elif "BECMG" in upper:
            period_type = "BECMG"
        elif "TEMPO" in upper:
            period_type = "TEMPO"
        else:
            raise ValueError(f"Unknown period label: {label!r}")

        # Extract DDHH/DDHH from the chunk text
        pr_m = _PERIOD_RE.search(chunk)
        if not pr_m:
            raise ValueError(f"No period time found in group: {chunk[:60]}")
        period_from = _resolve_ddhh(int(pr_m.group(1)), int(pr_m.group(2)), ref_dt)
        period_to   = _resolve_ddhh(int(pr_m.group(3)), int(pr_m.group(4)), ref_dt)
        if period_to <= period_from:
            period_to += timedelta(days=1)

    # --- Parse conditions from the chunk ---
    # Remove the group header tokens so only the condition tokens remain
    cond_text = _strip_group_header(chunk, period_type, probability)

    wind       = _parse_wind(cond_text)
    vis_sm, vis_gt = _parse_visibility_sm(cond_text)
    ceiling_ft, ceiling_coverage, sky_string = _parse_sky_layers(cond_text)
    wx         = _parse_weather_phenomena(cond_text)

    return {
        "period_type":         period_type,
        "period_seq":          seq,
        "valid_from":          period_from.isoformat(),
        "valid_to":            period_to.isoformat(),
        "wind_dir":            wind["wind_dir"],
        "wind_variable":       int(wind["wind_variable"]),
        "wind_speed":          wind["wind_speed"],
        "wind_gust":           wind["wind_gust"],
        "visibility_sm":       vis_sm,
        "visibility_gt":       int(vis_gt),
        "ceiling_ft":          ceiling_ft,
        "ceiling_coverage":    ceiling_coverage,
        "sky_string":          sky_string or None,
        "weather_phenomena":   wx if wx else [],
        "probability":         probability,
    }


def _strip_group_header(chunk: str, period_type: str, probability: Optional[int]) -> str:
    """
    Remove the group header tokens (FM…, BECMG, TEMPO, PROBxx, DDHH/DDHH)
    from the chunk text so only condition tokens remain for parsing.
    """
    text = chunk

    # Remove FM header
    text = _FM_TIME_RE.sub("", text)
    # Remove group-type keywords
    for kw in ("BECMG", "TEMPO", "NOSIG"):
        text = re.sub(rf'\b{kw}\b', "", text)
    # Remove PROB30 / PROB40
    text = re.sub(r'\bPROB\d{2}\b', "", text)
    # Remove DDHH/DDHH period time
    text = _PERIOD_RE.sub("", text)

    return text.strip()


# ---------------------------------------------------------------------------
# Flight category (used by both METAR parser and scoring module)
# ---------------------------------------------------------------------------

def _flight_category(ceiling_ft: Optional[int], visibility_sm: Optional[float]) -> str:
    """
    Derive the FAA flight category from ceiling and visibility.

    Category  Ceiling              Visibility
    --------  -------------------  ----------
    LIFR      < 500 ft AGL         OR < 1 SM
    IFR       500 – 999 ft AGL     OR 1 – < 3 SM
    MVFR      1 000 – 2 999 ft AGL OR 3 – < 5 SM
    VFR       ≥ 3 000 ft AGL       AND ≥ 5 SM

    A None ceiling means "unlimited" (no BKN/OVC/VV layer reported).
    """
    eff_ceiling = ceiling_ft if ceiling_ft is not None else 99_999
    eff_vis     = visibility_sm if visibility_sm is not None else 99.0

    if eff_ceiling < 500 or eff_vis < 1:
        return "LIFR"
    if eff_ceiling < 1_000 or eff_vis < 3:
        return "IFR"
    if eff_ceiling < 3_000 or eff_vis < 5:
        return "MVFR"
    return "VFR"


# ---------------------------------------------------------------------------
# Network fetch functions
# ---------------------------------------------------------------------------

def fetch_metars(icao: str, hours: int = 26) -> list[dict]:
    """
    Retrieve recent METARs for ``icao`` from aviationweather.gov.

    Parameters
    ----------
    icao   4-letter ICAO station identifier (e.g. "KORD").
    hours  How many hours back to retrieve (default 26 to cover a full TAF).

    Returns
    -------
    List of decoded METAR dicts (see parse_metar_raw() return format),
    each also containing a ``raw_text`` key.
    Observations are returned in chronological order (oldest first).
    """
    url = f"{BASE_URL}/metar"
    params = {
        "ids":    icao.upper(),
        "format": "json",
        "hours":  str(hours),
    }
    logger.info("Fetching METARs for %s (last %d h)", icao, hours)
    records = _get(url, params)

    results: list[dict] = []
    for rec in records:
        raw = rec.get("rawOb", "")
        if not raw:
            continue
        try:
            parsed = parse_metar_raw(raw)
        except Exception as exc:
            logger.warning("Failed to parse METAR %r: %s", raw[:60], exc)
            continue

        parsed["raw_text"] = raw
        parsed["airport_icao"] = icao.upper()
        results.append(parsed)

    # Sort oldest → newest
    results.sort(key=lambda r: r.get("observation_time") or "")
    return results


def fetch_tafs(icao: str) -> list[dict]:
    """
    Retrieve current and recent TAFs for ``icao`` from aviationweather.gov.

    The API returns the most recent TAF plus any amendments.  We request
    ``time=valid`` to get TAFs whose valid period overlaps the current time.

    Returns
    -------
    List of parsed TAF dicts (see parse_taf_raw() return format),
    sorted by issue_time ascending (oldest first).
    """
    url = f"{BASE_URL}/taf"
    params = {
        "ids":    icao.upper(),
        "format": "json",
        "time":   "valid",
    }
    logger.info("Fetching TAFs for %s", icao)
    records = _get(url, params)

    results: list[dict] = []
    for rec in records:
        raw = rec.get("rawTAF", "")
        if not raw:
            continue

        # Use the API's bulletin time as the reference anchor
        bulletin_ts = rec.get("bulletinTime") or rec.get("issueTime")
        try:
            ref_dt = datetime.fromisoformat(
                bulletin_ts.replace("Z", "+00:00")
            ) if bulletin_ts else None
        except Exception:
            ref_dt = None

        try:
            parsed = parse_taf_raw(raw, ref_dt=ref_dt)
        except Exception as exc:
            logger.warning("Failed to parse TAF %r: %s", raw[:60], exc)
            continue

        results.append(parsed)

    results.sort(key=lambda t: t.get("issue_time") or "")
    return results
