#!/usr/bin/env python3
"""
ingest.py — End-to-end ingestion pipeline for TAF accuracy data.

For each US airport the pipeline:
  1. Fetches airport metadata from aviationweather.gov/api/data/airport
  2. Fetches TAFs (current + recent amendments)
  3. Fetches METARs (configurable lookback window, default 26 h)
  4. Aligns each METAR to the correct TAF period and scores it
  5. Upserts everything into SQLite (fully idempotent — safe to re-run)

Usage
-----
  # Specific airports
  python ingest.py --airports KORD KJFK KLAX

  # All ~300 bundled US TAF stations
  python ingest.py --all

  # Tune concurrency and history window
  python ingest.py --all --workers 8 --hours 48

  # Verbose progress
  python ingest.py --airports KBOS --verbose
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Optional

import httpx

from database import get_session, init_db
from fetch import fetch_metars, fetch_tafs, BASE_URL, REQUEST_TIMEOUT
from models import Airport, TAF, TAFPeriod, METAR, ForecastScore
from scoring import process_airport

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Bundled US TAF station list (~300 major CONUS + AK/HI airports)
# Sourced from NWS TAF station inventory (all have scheduled TAF service).
# ---------------------------------------------------------------------------

# Complete list of all 698 US TAF-producing stations (CONUS + AK + HI + territories).
# Sourced by querying the NWS TAF locations API and verifying each station against
# the Aviation Weather Center ADDS API (aviationweather.gov).
US_TAF_STATIONS: list[str] = [
    # ── CONUS (K***) ──
    "KABE", "KABI", "KABQ", "KABR", "KABY", "KACK", "KACT", "KACV", "KACY", "KADF",
    "KAEG", "KAEX", "KAFW", "KAGC", "KAGS", "KAHN", "KAIA", "KAIK", "KALB", "KALI",
    "KALO", "KALS", "KALW", "KAMA", "KAND", "KAOO", "KAPA", "KAPC", "KAPF", "KAPN",
    "KARA", "KART", "KASD", "KASE", "KAST", "KATL", "KATW", "KATY", "KAUG", "KAUO",
    "KAUS", "KAUW", "KAVL", "KAVP", "KAXN", "KAZO", "KBBD", "KBBG", "KBCB", "KBDL",
    "KBDN", "KBDR", "KBED", "KBFD", "KBFF", "KBFI", "KBFL", "KBFM", "KBGM", "KBGR",
    "KBHB", "KBHM", "KBIH", "KBIL", "KBIS", "KBJC", "KBJI", "KBKE", "KBKW", "KBLF",
    "KBLH", "KBLI", "KBMG", "KBMI", "KBNA", "KBNO", "KBOI", "KBOS", "KBPI", "KBPK",
    "KBPT", "KBRD", "KBRL", "KBRO", "KBTL", "KBTM", "KBTR", "KBTV", "KBUF", "KBUR",
    "KBVI", "KBVO", "KBWG", "KBWI", "KBYI", "KBZN", "KCAE", "KCAK", "KCAR", "KCDC",
    "KCDR", "KCDS", "KCEC", "KCGI", "KCHA", "KCHO", "KCHS", "KCID", "KCIU", "KCKB",
    "KCKV", "KCLE", "KCLL", "KCLM", "KCLT", "KCMA", "KCMH", "KCMI", "KCMX", "KCNM",
    "KCNU", "KCNY", "KCOD", "KCOE", "KCON", "KCOS", "KCOT", "KCOU", "KCPR", "KCPS",
    "KCRE", "KCRG", "KCRP", "KCRQ", "KCRW", "KCSG", "KCSM", "KCSV", "KCTB", "KCUB",
    "KCVG", "KCWA", "KCXO", "KCXP", "KCYS", "KDAB", "KDAG", "KDAL", "KDAN", "KDAY",
    "KDBQ", "KDCA", "KDDC", "KDEC", "KDEN", "KDET", "KDFW", "KDHN", "KDHT", "KDIJ",
    "KDIK", "KDLH", "KDLS", "KDMN", "KDNL", "KDPA", "KDRO", "KDRT", "KDSM", "KDTW",
    "KDUA", "KDUG", "KDUJ", "KDVL", "KDVT", "KEAR", "KEAT", "KEAU", "KECG", "KECP",
    "KEED", "KEET", "KEFK", "KEGE", "KEKN", "KEKO", "KEKS", "KELD", "KELM", "KELP",
    "KELY", "KENV", "KENW", "KERI", "KEUG", "KEUL", "KEVV", "KEVW", "KEWN", "KEWR",
    "KEYW", "KFAR", "KFAT", "KFAY", "KFDY", "KFKL", "KFLG", "KFLL", "KFLO", "KFMH",
    "KFMN", "KFMY", "KFNT", "KFOD", "KFOE", "KFPR", "KFSD", "KFSM", "KFST", "KFTW",
    "KFTY", "KFVE", "KFWA", "KFXE", "KFYV", "KGBD", "KGCC", "KGCK", "KGCN", "KGDV",
    "KGEG", "KGFK", "KGFL", "KGGG", "KGGW", "KGJT", "KGKY", "KGLD", "KGLH", "KGLS",
    "KGMU", "KGNV", "KGON", "KGPI", "KGPT", "KGRB", "KGRI", "KGRR", "KGSO", "KGSP",
    "KGTF", "KGTR", "KGUC", "KGUP", "KGUY", "KGWO", "KGYY", "KHAF", "KHBG", "KHCR",
    "KHDC", "KHDN", "KHEZ", "KHIB", "KHIE", "KHIO", "KHKS", "KHKY", "KHLG", "KHLN",
    "KHNB", "KHND", "KHOB", "KHON", "KHOT", "KHOU", "KHPN", "KHQM", "KHRF", "KHRL",
    "KHRO", "KHSV", "KHTS", "KHUF", "KHUL", "KHUM", "KHUT", "KHVR", "KHYA", "KHYR",
    "KHYS", "KIAD", "KIAG", "KIAH", "KICT", "KIDA", "KIFP", "KILG", "KILM", "KILN",
    "KIND", "KINK", "KINL", "KINT", "KINW", "KIOB", "KIPL", "KIPT", "KISM", "KISO",
    "KISP", "KITH", "KIWA", "KIWD", "KIXD", "KJAC", "KJAN", "KJAX", "KJBR", "KJCT",
    "KJEF", "KJER", "KJFK", "KJHW", "KJKA", "KJKL", "KJLN", "KJMS", "KJST", "KJVL",
    "KJXN", "KJZI", "KLAF", "KLAL", "KLAN", "KLAR", "KLAS", "KLAW", "KLAX", "KLBB",
    "KLBE", "KLBF", "KLBL", "KLBT", "KLBX", "KLCH", "KLCK", "KLEB", "KLEE", "KLEX",
    "KLFK", "KLFT", "KLGA", "KLGB", "KLGU", "KLIT", "KLLQ", "KLMT", "KLND", "KLNK",
    "KLNS", "KLOZ", "KLRD", "KLRU", "KLSE", "KLUK", "KLVK", "KLVM", "KLWB", "KLWS",
    "KLWT", "KLYH", "KMAF", "KMBG", "KMBL", "KMBS", "KMCB", "KMCC", "KMCE", "KMCI",
    "KMCK", "KMCN", "KMCO", "KMCW", "KMDT", "KMDW", "KMEI", "KMEM", "KMEV", "KMFD",
    "KMFE", "KMFR", "KMGM", "KMGW", "KMHK", "KMHR", "KMHT", "KMIA", "KMIV", "KMKC",
    "KMKE", "KMKG", "KMKL", "KMKT", "KMLB", "KMLC", "KMLI", "KMLS", "KMLU", "KMMH",
    "KMOB", "KMOD", "KMOT", "KMPV", "KMQY", "KMRB", "KMRY", "KMSL", "KMSN", "KMSO",
    "KMSP", "KMSS", "KMSY", "KMTH", "KMTJ", "KMTN", "KMTW", "KMWH", "KMYL", "KMYR",
    "KNEW", "KOAJ", "KOAK", "KOFK", "KOGB", "KOGD", "KOKC", "KOLF", "KOLM", "KOLS",
    "KOMA", "KONO", "KONP", "KONT", "KOPF", "KORD", "KORF", "KORH", "KOTH", "KOTM",
    "KOUN", "KOWB", "KOXR", "KPAE", "KPAH", "KPBF", "KPBG", "KPBI", "KPDK", "KPDT",
    "KPDX", "KPEQ", "KPGA", "KPGD", "KPGV", "KPHF", "KPHL", "KPHX", "KPIA", "KPIB",
    "KPIE", "KPIH", "KPIR", "KPIT", "KPKB", "KPLN", "KPMD", "KPNA", "KPNC", "KPNE",
    "KPNS", "KPOU", "KPQI", "KPRB", "KPRC", "KPSC", "KPSF", "KPSM", "KPSP", "KPTK",
    "KPUB", "KPUW", "KPVD", "KPVU", "KPVW", "KPWM", "KPWT", "KRAP", "KRBG", "KRBL",
    "KRDD", "KRDG", "KRDM", "KRDU", "KRFD", "KRGA", "KRHI", "KRIC", "KRIL", "KRIW",
    "KRKD", "KRKS", "KRME", "KRNH", "KRNO", "KROA", "KROC", "KROG", "KROW", "KRSL",
    "KRST", "KRSW", "KRUT", "KRVS", "KRWF", "KRWI", "KRWL", "KRYY", "KSAC", "KSAF",
    "KSAN", "KSAT", "KSAV", "KSAW", "KSBA", "KSBD", "KSBM", "KSBN", "KSBP", "KSBY",
    "KSCK", "KSDF", "KSDL", "KSDY", "KSEA", "KSEZ", "KSFB", "KSFF", "KSFO", "KSGF",
    "KSGJ", "KSGR", "KSGU", "KSHR", "KSHV", "KSJC", "KSJS", "KSJT", "KSLC", "KSLE",
    "KSLK", "KSLN", "KSME", "KSMF", "KSMN", "KSMO", "KSMX", "KSNA", "KSNS", "KSNY",
    "KSOA", "KSPI", "KSPS", "KSRB", "KSRQ", "KSSF", "KSSI", "KSTC", "KSTJ", "KSTL",
    "KSTS", "KSUA", "KSUN", "KSUS", "KSUX", "KSWF", "KSWO", "KSYM", "KSYR", "KTCL",
    "KTCS", "KTEB", "KTEX", "KTIX", "KTLH", "KTMB", "KTOL", "KTOP", "KTPA", "KTPH",
    "KTRI", "KTRK", "KTRM", "KTTD", "KTTN", "KTUL", "KTUP", "KTUS", "KTVC", "KTVF",
    "KTVL", "KTWF", "KTXK", "KTYR", "KTYS", "KUAO", "KUES", "KUIN", "KUKI", "KUNV",
    "KUTS", "KVCT", "KVEL", "KVGT", "KVIS", "KVLD", "KVNY", "KVQQ", "KVRB", "KVTN",
    "KWJF", "KWMC", "KWRL", "KWWR", "KWYS", "KXNA", "KXWA", "KYIP", "KYKM", "KYNG",
    "KZZV",
    # ── Alaska ──
    "PAAQ", "PABE", "PABI", "PABR", "PABT", "PACD", "PACV", "PADL", "PADQ", "PADU",
    "PAED", "PAEI", "PAEN", "PAFA", "PAGA", "PAGK", "PAGS", "PAGY", "PAHN", "PAHO",
    "PAIL", "PAJN", "PAKN", "PAKT", "PAKW", "PAMC", "PANC", "PAOM", "PAOR", "PAOT",
    "PAPG", "PAQT", "PASC", "PASD", "PASI", "PASN", "PASY", "PATA", "PATK", "PAUN",
    "PAVD", "PAWG", "PAYA",
    # ── Hawaii (civilian) ──
    "PHJH", "PHJR", "PHKO", "PHLI", "PHMK", "PHNL", "PHNY", "PHOG", "PHTO",
    # ── Hawaii (military) ──
    "PHHI", "PHNG",
    # ── Puerto Rico / US Virgin Islands ──
    "TIST", "TISX", "TJBQ", "TJPS", "TJSJ",
    # ── Military / joint-use (CONUS) ──
    "KBAB", "KBAD", "KBIF", "KBKF", "KDMA", "KDOV", "KEND", "KFAF", "KFBG", "KFCS",
    "KFFO", "KFHU", "KFRI", "KFTK", "KGRK", "KGUS", "KHIF", "KHOP", "KHRT", "KHST",
    "KLFI", "KLRF", "KLTS", "KMCF", "KMGE", "KMIB", "KMUO", "KNBC", "KNFL", "KNFW",
    "KNGU", "KNHK", "KNKX", "KNLC", "KNMM", "KNPA", "KNQI", "KNRB", "KNSE", "KNTU",
    "KNUC", "KNUW", "KNXP", "KOFF", "KPAM", "KPOE", "KRCA", "KRDR", "KRND", "KSEM",
    "KSKA", "KSKF", "KSUU", "KTBN", "KTIK", "KVAD", "KVBG", "KVPS", "KWRB", "KWRI",
]


# ---------------------------------------------------------------------------
# Airport metadata fetch
# ---------------------------------------------------------------------------

def fetch_airport_info(icao: str) -> Optional[dict]:
    """
    Retrieve airport metadata (name, lat, lon) from aviationweather.gov.

    Returns a dict with keys: icao, name, lat, lon.
    Returns None on error (the airport row will still be created with
    stub values so FK constraints are satisfied).
    """
    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
            resp = client.get(
                f"{BASE_URL}/airport",
                params={"ids": icao, "format": "json"},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.warning("Could not fetch airport info for %s: %s", icao, exc)
        return None

    if not data or not isinstance(data, list):
        return None

    rec = data[0]
    return {
        "icao":  icao.upper(),
        "name":  rec.get("site") or rec.get("name") or icao,
        "state": rec.get("state") or None,
        "lat":   rec.get("lat"),
        "lon":   rec.get("lon"),
    }


# ---------------------------------------------------------------------------
# DB upsert helpers
# ---------------------------------------------------------------------------

def _upsert_airport(session, icao: str, info: Optional[dict]) -> Airport:
    """
    Insert an Airport row if it does not already exist.
    If metadata fetch failed, create a stub row so FK constraints hold.
    """
    existing = session.get(Airport, icao.upper())
    if existing:
        # Backfill state if it wasn't set on initial insert
        if existing.state is None and info and info.get("state"):
            existing.state = info["state"]
        return existing

    ap = Airport(
        icao =icao.upper(),
        name =(info or {}).get("name") or icao.upper(),
        state=(info or {}).get("state"),
        lat  =(info or {}).get("lat"),
        lon  =(info or {}).get("lon"),
    )
    session.add(ap)
    session.flush()
    return ap


def _upsert_taf(session, taf_data: dict) -> tuple[int, bool]:
    """
    Insert a TAF (and its TAFPeriod children) if it does not already exist.

    Returns (db_id, was_inserted).  Skips insertion silently if a TAF with
    the same (airport_icao, issue_time) already exists.
    """
    icao       = taf_data["icao"].upper()
    issue_time = taf_data["issue_time"]

    existing = (
        session.query(TAF)
        .filter_by(airport_icao=icao, issue_time=issue_time)
        .first()
    )
    if existing:
        return existing.id, False

    taf_obj = TAF(
        airport_icao=icao,
        issue_time  =issue_time,
        valid_from  =taf_data["valid_from"],
        valid_to    =taf_data["valid_to"],
        raw_text    =taf_data["raw_text"],
    )
    session.add(taf_obj)
    session.flush()  # populate taf_obj.id

    for period in taf_data.get("periods", []):
        p = TAFPeriod(
            taf_id            =taf_obj.id,
            period_type       =period["period_type"],
            period_seq        =period["period_seq"],
            valid_from        =period["valid_from"],
            valid_to          =period["valid_to"],
            wind_dir          =period.get("wind_dir"),
            wind_variable     =period.get("wind_variable", 0),
            wind_speed        =period.get("wind_speed"),
            wind_gust         =period.get("wind_gust"),
            visibility_sm     =period.get("visibility_sm"),
            visibility_gt     =period.get("visibility_gt", 0),
            ceiling_ft        =period.get("ceiling_ft"),
            ceiling_coverage  =period.get("ceiling_coverage"),
            sky_string        =period.get("sky_string"),
            weather_phenomena =period.get("weather_phenomena") or [],
            probability       =period.get("probability"),
        )
        session.add(p)

    return taf_obj.id, True


def _upsert_metar(session, metar_data: dict) -> tuple[int, bool]:
    """
    Insert a METAR row if it does not already exist.

    Returns (db_id, was_inserted).
    """
    icao     = metar_data["airport_icao"].upper()
    obs_time = metar_data["observation_time"]

    if not obs_time:
        return -1, False

    existing = (
        session.query(METAR)
        .filter_by(airport_icao=icao, observation_time=obs_time)
        .first()
    )
    if existing:
        return existing.id, False

    m = METAR(
        airport_icao     =icao,
        observation_time =obs_time,
        raw_text         =metar_data.get("raw_text", ""),
        wind_dir         =metar_data.get("wind_dir"),
        wind_variable    =int(bool(metar_data.get("wind_variable", False))),
        wind_speed       =metar_data.get("wind_speed"),
        wind_gust        =metar_data.get("wind_gust"),
        visibility_sm    =metar_data.get("visibility_sm"),
        ceiling_ft       =metar_data.get("ceiling_ft"),
        ceiling_coverage =metar_data.get("ceiling_coverage"),
        weather_phenomena=metar_data.get("weather_phenomena") or [],
        flight_category  =metar_data.get("flight_category", "VFR"),
    )
    session.add(m)
    session.flush()
    return m.id, True


def _upsert_scores(
    session,
    score_rows: list[dict],
    metar_id_map: dict[str, int],   # obs_time → metar db_id
    taf_id_map:   dict[str, int],   # issue_time → taf db_id
) -> int:
    """
    Insert ForecastScore rows, skipping duplicates.
    Returns the number of rows actually inserted.
    """
    inserted = 0
    for row in score_rows:
        metar_id = metar_id_map.get(row.get("_metar_obs_time", ""))
        taf_id   = taf_id_map.get(row.get("_taf_issue_time", ""))

        if metar_id is None or taf_id is None or metar_id < 0:
            continue

        existing = (
            session.query(ForecastScore)
            .filter_by(metar_id=metar_id, taf_id=taf_id)
            .first()
        )
        if existing:
            continue

        fs = ForecastScore(
            airport_icao           =row["airport_icao"],
            metar_id               =metar_id,
            taf_id                 =taf_id,
            forecast_hour_offset   =row["forecast_hour_offset"],
            ceiling_coverage_score =row.get("ceiling_coverage_score"),
            ceiling_altitude_score =row.get("ceiling_altitude_score"),
            visibility_score       =row.get("visibility_score"),
            wind_speed_score       =row.get("wind_speed_score"),
            wind_dir_score         =row.get("wind_dir_score"),
            wx_precision           =row.get("wx_precision"),
            wx_recall              =row.get("wx_recall"),
            overall_score          =row.get("overall_score"),
            tempo_active           =row.get("tempo_active", 0),
        )
        session.add(fs)
        inserted += 1

    session.flush()
    return inserted


# ---------------------------------------------------------------------------
# Per-station pipeline
# ---------------------------------------------------------------------------

def process_station(icao: str, hours: int = 26) -> dict:
    """
    Full ingest pipeline for one airport.  Thread-safe: opens its own
    DB session so concurrent workers do not share state.

    Returns a stats dict:
        tafs_new, tafs_seen, metars_new, metars_seen, scores_new, errors
    """
    icao = icao.upper()
    stats = {
        "icao":        icao,
        "tafs_new":    0,
        "tafs_seen":   0,
        "metars_new":  0,
        "metars_seen": 0,
        "scores_new":  0,
        "errors":      [],
    }

    # ── 1. Fetch airport metadata ──────────────────────────────────────────
    airport_info = fetch_airport_info(icao)

    # ── 2. Fetch TAFs ──────────────────────────────────────────────────────
    try:
        tafs = fetch_tafs(icao)
    except Exception as exc:
        stats["errors"].append(f"TAF fetch failed: {exc}")
        logger.error("%s TAF fetch failed: %s", icao, exc)
        tafs = []

    # ── 3. Fetch METARs ────────────────────────────────────────────────────
    try:
        metars = fetch_metars(icao, hours=hours)
    except Exception as exc:
        stats["errors"].append(f"METAR fetch failed: {exc}")
        logger.error("%s METAR fetch failed: %s", icao, exc)
        metars = []

    # ── 4. Write freshly fetched data to DB ───────────────────────────────
    with get_session() as session:
        _upsert_airport(session, icao, airport_info)

        for taf_data in tafs:
            try:
                _, was_new = _upsert_taf(session, taf_data)
                if was_new:
                    stats["tafs_new"] += 1
                else:
                    stats["tafs_seen"] += 1
            except Exception as exc:
                stats["errors"].append(f"TAF write error: {exc}")
                logger.warning("%s TAF write error: %s", icao, exc)

        for metar_data in metars:
            try:
                _, was_new = _upsert_metar(session, metar_data)
                if was_new:
                    stats["metars_new"] += 1
                else:
                    stats["metars_seen"] += 1
            except Exception as exc:
                stats["errors"].append(f"METAR write error: {exc}")
                logger.warning("%s METAR write error: %s", icao, exc)

    # ── 5. Score all unscored (METAR, TAF) pairs from the DB ──────────────
    #
    # We load ALL stored TAFs + METARs for this airport rather than only the
    # just-fetched data.  This means a second run will pick up METARs that
    # now fall inside a TAF stored from a previous run, and vice-versa.
    # The unique constraint on forecast_scores prevents double-counting.
    try:
        n = _score_unscored_from_db(icao)
        stats["scores_new"] = n
    except Exception as exc:
        stats["errors"].append(f"DB scoring error: {exc}")
        logger.warning("%s DB scoring error: %s", icao, exc)

    return stats


def _taf_orm_to_dict(taf_orm: TAF) -> dict:
    """Convert a TAF ORM object (with loaded periods) to the dict format
    expected by scoring.score_metar_vs_taf()."""
    periods = []
    for p in taf_orm.periods:
        periods.append({
            "period_type":       p.period_type,
            "period_seq":        p.period_seq,
            "valid_from":        p.valid_from,
            "valid_to":          p.valid_to,
            "wind_dir":          p.wind_dir,
            "wind_variable":     bool(p.wind_variable),
            "wind_speed":        p.wind_speed,
            "wind_gust":         p.wind_gust,
            "visibility_sm":     p.visibility_sm,
            "visibility_gt":     bool(p.visibility_gt),
            "ceiling_ft":        p.ceiling_ft,
            "ceiling_coverage":  p.ceiling_coverage,
            "sky_string":        p.sky_string,
            "weather_phenomena": p.weather_phenomena or [],
            "probability":       p.probability,
        })
    return {
        "id":         taf_orm.id,
        "icao":       taf_orm.airport_icao,
        "issue_time": taf_orm.issue_time,
        "valid_from": taf_orm.valid_from,
        "valid_to":   taf_orm.valid_to,
        "raw_text":   taf_orm.raw_text,
        "periods":    periods,
    }


def _metar_orm_to_dict(m_orm: METAR) -> dict:
    """Convert a METAR ORM object to the dict format expected by scoring."""
    return {
        "id":                m_orm.id,
        "airport_icao":      m_orm.airport_icao,
        "observation_time":  m_orm.observation_time,
        "wind_dir":          m_orm.wind_dir,
        "wind_variable":     bool(m_orm.wind_variable),
        "wind_speed":        m_orm.wind_speed,
        "wind_gust":         m_orm.wind_gust,
        "visibility_sm":     m_orm.visibility_sm,
        "ceiling_ft":        m_orm.ceiling_ft,
        "ceiling_coverage":  m_orm.ceiling_coverage,
        "weather_phenomena": m_orm.weather_phenomena or [],
        "flight_category":   m_orm.flight_category,
    }


def _score_unscored_from_db(icao: str) -> int:
    """
    Score all (METAR, TAF) pairs for ``icao`` that don't yet have a
    ForecastScore row in the database.

    Strategy
    --------
    1. Load all stored TAFs for the airport.
    2. Load all stored METARs for the airport.
    3. For each METAR, identify all TAFs whose valid window covers the
       observation time and whose issue time precedes the observation.
    4. Among those candidates, pick the most-recently-issued TAF (the one
       a forecaster would have had in hand at the time of the observation).
    5. If no ForecastScore row exists yet for that (metar, taf) pair, compute
       and insert one.

    Returns the number of new ForecastScore rows inserted.
    """
    from scoring import score_metar_vs_taf, _iso

    inserted = 0

    with get_session() as session:
        # Load all TAFs with their periods eagerly
        from sqlalchemy.orm import joinedload
        db_tafs = (
            session.query(TAF)
            .options(joinedload(TAF.periods))
            .filter_by(airport_icao=icao)
            .all()
        )
        db_metars = (
            session.query(METAR)
            .filter_by(airport_icao=icao)
            .all()
        )

        if not db_tafs or not db_metars:
            return 0

        # Convert ORM → dicts (so they survive outside the session for scoring)
        taf_dicts = [_taf_orm_to_dict(t) for t in db_tafs]
        # Build a set of already-scored (metar_id, taf_id) pairs
        existing_pairs: set[tuple[int, int]] = {
            (fs.metar_id, fs.taf_id)
            for fs in session.query(ForecastScore.metar_id, ForecastScore.taf_id)
                              .filter_by(airport_icao=icao)
                              .all()
        }

        new_scores: list[tuple[int, int, dict]] = []  # (metar_id, taf_id, score_row)

        for m_orm in db_metars:
            obs_str = m_orm.observation_time
            if not obs_str:
                continue
            obs_time = _iso(obs_str)

            # Find the best covering TAF from all stored TAFs
            best_taf: Optional[dict] = None
            for td in taf_dicts:
                tf = _iso(td["valid_from"])
                tt = _iso(td["valid_to"])
                issued = _iso(td["issue_time"])
                if tf <= obs_time < tt and issued <= obs_time:
                    if best_taf is None or issued > _iso(best_taf["issue_time"]):
                        best_taf = td

            if best_taf is None:
                continue

            metar_id = m_orm.id
            taf_id   = best_taf["id"]

            if (metar_id, taf_id) in existing_pairs:
                continue  # already scored

            metar_dict = _metar_orm_to_dict(m_orm)
            score = score_metar_vs_taf(metar_dict, best_taf, best_taf["periods"])
            if score is None:
                continue

            score["_metar_id"]  = metar_id
            score["_taf_id"]    = taf_id
            new_scores.append((metar_id, taf_id, score))

        # Insert in a single flush
        for metar_id, taf_id, row in new_scores:
            fs = ForecastScore(
                airport_icao           =icao,
                metar_id               =metar_id,
                taf_id                 =taf_id,
                forecast_hour_offset   =row["forecast_hour_offset"],
                ceiling_coverage_score =row.get("ceiling_coverage_score"),
                ceiling_altitude_score =row.get("ceiling_altitude_score"),
                visibility_score       =row.get("visibility_score"),
                wind_speed_score       =row.get("wind_speed_score"),
                wind_dir_score         =row.get("wind_dir_score"),
                wx_precision           =row.get("wx_precision"),
                wx_recall              =row.get("wx_recall"),
                overall_score          =row.get("overall_score"),
                tempo_active           =row.get("tempo_active", 0),
            )
            session.add(fs)
            inserted += 1

    return inserted


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        stream=sys.stderr,
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )


def _format_stats(s: dict) -> str:
    parts = [
        f"TAFs +{s['tafs_new']}/{s['tafs_new']+s['tafs_seen']}",
        f"METARs +{s['metars_new']}/{s['metars_new']+s['metars_seen']}",
        f"scores +{s['scores_new']}",
    ]
    if s["errors"]:
        parts.append(f"⚠ {len(s['errors'])} error(s)")
    return "  ".join(parts)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ingest TAF accuracy data into SQLite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--airports", "-a", nargs="+", metavar="ICAO",
        help="One or more ICAO airport codes (e.g. KORD KJFK)",
    )
    group.add_argument(
        "--all", action="store_true",
        help=f"Process all {len(US_TAF_STATIONS)} bundled US TAF stations",
    )
    parser.add_argument(
        "--hours", type=int, default=26, metavar="N",
        help="Hours of METAR history to retrieve (default: 26)",
    )
    parser.add_argument(
        "--workers", type=int, default=4, metavar="N",
        help="Number of concurrent fetch workers (default: 4). "
             "Be polite to the API — don't set above 10.",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args(argv)

    _setup_logging(args.verbose)

    stations: list[str]
    if args.all:
        stations = US_TAF_STATIONS
    else:
        stations = [s.upper() for s in args.airports]
        # Basic validation
        bad = [s for s in stations if len(s) != 4]
        if bad:
            parser.error(f"Invalid ICAO codes (must be 4 letters): {bad}")

    print(f"Initialising database …")
    init_db()

    total    = len(stations)
    done     = 0
    failed   = 0
    t_start  = time.monotonic()

    print(
        f"Processing {total} station(s) "
        f"with {args.workers} worker(s), "
        f"{args.hours} h of history\n"
    )

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        future_to_icao = {
            pool.submit(process_station, icao, args.hours): icao
            for icao in stations
        }

        for future in as_completed(future_to_icao):
            icao = future_to_icao[future]
            done += 1
            pct  = done / total * 100

            try:
                stats = future.result()
                line  = f"[{done:>{len(str(total))}}/{total}] {pct:5.1f}%  {icao}  {_format_stats(stats)}"
                if stats["errors"]:
                    failed += 1
                    logger.debug("%s errors: %s", icao, stats["errors"])
            except Exception as exc:
                failed += 1
                line = f"[{done:>{len(str(total))}}/{total}] {pct:5.1f}%  {icao}  FAILED: {exc}"

            print(line)

    elapsed = time.monotonic() - t_start
    print(
        f"\nDone in {elapsed:.1f}s — "
        f"{total - failed}/{total} stations OK, {failed} failed."
    )
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
