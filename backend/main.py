"""
main.py — FastAPI server for the TAF accuracy dashboard.

Endpoints
---------
  GET  /health                        Liveness check
  GET  /airports                      All airports in DB with summary stats
  GET  /airport/{icao}                Full summary for one airport
  GET  /airport/{icao}/by-hour        Accuracy bucketed by forecast-hour offset
  GET  /airport/{icao}/recent         Last N scored observations
  GET  /leaderboard                   All airports ranked by accuracy
  POST /ingest/{icao}                 Trigger a background fetch+score for one airport
  POST /ingest/batch                  Trigger background ingest for a list of airports

Run
---
  uvicorn main:app --reload --port 8000
"""

from __future__ import annotations

import logging
import os
import time
from typing import Optional

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import Float, cast, func, text

from database import get_session, init_db
from ingest import process_station, US_TAF_STATIONS, MILITARY_STATIONS, _taf_orm_to_dict, _metar_orm_to_dict
from models import Airport, ApiCache, ForecastScore, METAR, TAF, AirportStats, LeadTimeStats, DailyStats

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="TAF Accuracy API",
    description="Measures how accurately Terminal Aerodrome Forecasts match METAR observations.",
    version="1.0.0",
)

# Allow the React dev server and any origin specified via CORS_ORIGINS env var.
# In production, set CORS_ORIGINS to your Vercel URL, e.g.:
#   CORS_ORIGINS=https://windcheck.vercel.app
_default_origins = ["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173"]
_extra = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
_allowed_origins = _default_origins + _extra

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


_INGEST_INTERVAL_HOURS = 6  # run a full batch ingest every N hours


@app.on_event("startup")
def _startup() -> None:
    logging.basicConfig(level=logging.INFO)
    if not _INGEST_KEY:
        raise RuntimeError("INGEST_API_KEY environment variable is not set — refusing to start.")
    init_db()
    import threading
    threading.Thread(target=_warm_caches,    daemon=True).start()
    threading.Thread(target=_ingest_scheduler, daemon=True).start()


def _ingest_scheduler() -> None:
    """Background thread: run a full ingest of all US TAF stations every N hours.

    Airports are processed sequentially with a short delay between each to avoid
    overwhelming the aviationweather.gov API with concurrent requests.
    """
    import time as _time
    _time.sleep(10)  # let startup finish before first run
    while True:
        logger.info("Scheduler: starting full ingest of %d stations", len(US_TAF_STATIONS))
        for icao in US_TAF_STATIONS:
            if icao not in _ingesting:
                _ingesting.add(icao)
                _run_ingest(icao)
            _time.sleep(1.5)  # ~1.5s between airports → full cycle takes ~19 min
        logger.info("Scheduler: full ingest complete, sleeping %dh", _INGEST_INTERVAL_HOURS)
        _time.sleep(_INGEST_INTERVAL_HOURS * 3600)


def _warm_caches() -> None:
    """Pre-populate caches after startup so the first user request is fast."""
    import time as _time
    _time.sleep(2)  # let uvicorn finish binding
    for name, fn, kwargs in [
        ("leaderboard",          leaderboard,                 {"sort_by": "overall_score", "min_obs": 5, "limit": 1000, "state": None, "military": False, "wfo": None, "climate_region": None}),
        ("map-data",             map_data,                    {"min_obs": 1}),
        ("analytics",            analytics,                   {}),
        ("lead-time",            analytics_lead_time,         {}),
        ("daily-comparisons",    analytics_daily_comparisons, {}),
    ]:
        try:
            logger.info("Warming %s cache...", name)
            fn(**kwargs)
            logger.info("Warmed %s cache.", name)
        except Exception as exc:
            logger.error("Cache warm-up failed for %s: %s", name, exc, exc_info=True)


_INGEST_KEY = os.getenv("INGEST_API_KEY", "")

def _require_ingest_key(x_api_key: str = Header(default="")):
    """Dependency that enforces the INGEST_API_KEY on write endpoints."""
    if not _INGEST_KEY or x_api_key != _INGEST_KEY:
        raise HTTPException(401, "Invalid or missing X-Api-Key header")


# ---------------------------------------------------------------------------
# Pydantic response models
# ---------------------------------------------------------------------------

class ScoreSummary(BaseModel):
    """Aggregated accuracy scores across all observations."""
    observation_count:      int
    overall_score:          Optional[float]
    ceiling_coverage_score: Optional[float]
    ceiling_altitude_score: Optional[float]
    visibility_score:       Optional[float]
    wind_speed_score:       Optional[float]
    wind_dir_score:         Optional[float]
    wx_precision:           Optional[float]
    wx_recall:              Optional[float]


class AmendmentStats(BaseModel):
    total_tafs:        int
    amendment_count:   int
    correction_count:  int
    amendment_pct:     float  # % of TAFs that were amendments
    original_score:    Optional[float]   # avg overall score for original TAFs
    amendment_score:   Optional[float]   # avg overall score for amended TAFs


class AirportDetail(BaseModel):
    icao:       str
    name:       Optional[str]
    lat:        Optional[float]
    lon:        Optional[float]
    summary:    ScoreSummary
    amendments: AmendmentStats


class HourBucket(BaseModel):
    """Accuracy metrics for one integer forecast-hour bucket (e.g. hour=3 covers offsets 3.0–3.99)."""
    hour:                   int
    count:                  int
    overall_score:          Optional[float]
    ceiling_coverage_score: Optional[float]
    ceiling_altitude_score: Optional[float]
    visibility_score:       Optional[float]
    wind_speed_score:       Optional[float]
    wind_dir_score:         Optional[float]


class RecentObservation(BaseModel):
    observation_time:       str
    forecast_hour_offset:   float
    flight_category:        Optional[str]
    overall_score:          Optional[float]
    ceiling_coverage_score: Optional[float]
    ceiling_altitude_score: Optional[float]
    visibility_score:       Optional[float]
    wind_speed_score:       Optional[float]
    wind_dir_score:         Optional[float]
    tempo_active:           bool


class LeaderboardEntry(BaseModel):
    rank:                   int
    icao:                   str
    name:                   Optional[str]
    state:                  Optional[str]
    wfo:                    Optional[str]
    climate_region:         Optional[str]
    lat:                    Optional[float]
    lon:                    Optional[float]
    is_military:            bool
    observation_count:      int
    overall_score:          Optional[float]
    ceiling_coverage_score: Optional[float]
    ceiling_altitude_score: Optional[float]
    visibility_score:       Optional[float]
    wind_speed_score:       Optional[float]
    wind_dir_score:         Optional[float]
    amendment_pct:          Optional[float]
    ceiling_coverage_diff:  Optional[float]
    ceiling_altitude_diff:  Optional[float]
    visibility_diff:        Optional[float]
    wind_speed_diff:        Optional[float]
    wind_dir_diff:          Optional[float]


class IngestResponse(BaseModel):
    status:   str   # "queued" | "skipped"
    airports: list[str]


# ---------------------------------------------------------------------------
# Helper — convert SQLAlchemy Row → rounded dict
# ---------------------------------------------------------------------------

def _round(val: Optional[float], digits: int = 3) -> Optional[float]:
    return round(val, digits) if val is not None else None


def _summary_from_rows(rows) -> ScoreSummary:
    """
    Build a ScoreSummary from a single SQLAlchemy aggregate result row.
    The row must expose the aliased columns produced by _score_agg_query().
    """
    if rows is None:
        return ScoreSummary(
            observation_count=0,
            overall_score=None, ceiling_score=None, visibility_score=None,
            wind_speed_score=None, wind_dir_score=None,
            wx_precision=None, wx_recall=None,
        )
    return ScoreSummary(
        observation_count      =rows.cnt or 0,
        overall_score          =_round(rows.overall),
        ceiling_coverage_score =_round(rows.ceil_cov),
        ceiling_altitude_score =_round(rows.ceil_alt),
        visibility_score       =_round(rows.visibility),
        wind_speed_score       =_round(rows.wind_speed),
        wind_dir_score         =_round(rows.wind_dir),
        wx_precision           =_round(rows.wx_prec),
        wx_recall              =_round(rows.wx_rec),
    )


# ---------------------------------------------------------------------------
# Reusable aggregate columns (avoid repetition in queries)
# ---------------------------------------------------------------------------

def _score_agg_cols():
    """SQLAlchemy column expressions for the standard aggregate score set."""
    return [
        func.count(ForecastScore.id)                        .label("cnt"),
        func.avg(ForecastScore.overall_score)             .label("overall"),
        func.avg(ForecastScore.ceiling_coverage_score)    .label("ceil_cov"),
        func.avg(ForecastScore.ceiling_altitude_score)    .label("ceil_alt"),
        func.avg(ForecastScore.visibility_score)          .label("visibility"),
        func.avg(ForecastScore.wind_speed_score)          .label("wind_speed"),
        func.avg(ForecastScore.wind_dir_score)            .label("wind_dir"),
        func.avg(ForecastScore.wx_precision)              .label("wx_prec"),
        func.avg(ForecastScore.wx_recall)                 .label("wx_rec"),
        func.avg(ForecastScore.ceiling_coverage_diff)     .label("ceil_cov_diff"),
        func.avg(ForecastScore.ceiling_altitude_diff)     .label("ceil_alt_diff"),
        func.avg(ForecastScore.visibility_diff)           .label("vis_diff"),
        func.avg(ForecastScore.wind_speed_diff)           .label("wind_spd_diff"),
        func.avg(ForecastScore.wind_dir_diff)             .label("wind_dir_diff"),
    ]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/stats")
def stats():
    with get_session() as session:
        row = session.execute(
            text("SELECT MIN(observation_time) FROM metars")
        ).fetchone()
        oldest = row[0] if row else None
    return {"tracking_since": oldest}


# ── /airports ───────────────────────────────────────────────────────────────

@app.get("/airports", response_model=list[LeaderboardEntry])
def list_airports(min_obs: int = Query(1, ge=1, description="Minimum observations to include")):
    """
    Return every airport in the database that has at least ``min_obs``
    scored observations, ordered by overall accuracy descending.
    """
    with get_session() as session:
        rows = (
            session.query(
                Airport.icao,
                Airport.name,
                *_score_agg_cols(),
            )
            .join(ForecastScore, Airport.icao == ForecastScore.airport_icao)
            .group_by(Airport.icao, Airport.name)
            .having(func.count(ForecastScore.id) >= min_obs)
            .order_by(func.avg(ForecastScore.overall_score).desc().nullslast())
            .all()
        )

    return [
        LeaderboardEntry(
            rank                   =i + 1,
            icao                   =r.icao,
            name                   =r.name,
            observation_count      =r.cnt,
            overall_score          =_round(r.overall),
            ceiling_coverage_score =_round(r.ceil_cov),
            ceiling_altitude_score =_round(r.ceil_alt),
            visibility_score       =_round(r.visibility),
            wind_speed_score       =_round(r.wind_speed),
            wind_dir_score         =_round(r.wind_dir),
        )
        for i, r in enumerate(rows)
    ]


# ── /airport/{icao} ─────────────────────────────────────────────────────────

@app.get("/airport/{icao}", response_model=AirportDetail)
def airport_detail(icao: str):
    """
    Return full accuracy summary for one airport.

    404 if the airport has no scored observations.
    """
    icao = icao.upper()
    with get_session() as session:
        ap = session.get(Airport, icao)
        ap_name = ap.name if ap else None
        ap_lat  = ap.lat  if ap else None
        ap_lon  = ap.lon  if ap else None

        agg = (
            session.query(*_score_agg_cols())
            .filter(ForecastScore.airport_icao == icao)
            .one()
        )

        # Amendment stats: count TAFs and compare scores by type
        amd_rows = session.execute(text("""
            SELECT
                COUNT(*)                                                          AS total,
                SUM(t.is_amendment)                                               AS amd_count,
                SUM(t.is_correction)                                              AS cor_count,
                AVG(CASE WHEN t.is_amendment = 0 AND t.is_correction = 0
                         THEN fs.overall_score END)                               AS orig_score,
                AVG(CASE WHEN t.is_amendment = 1
                         THEN fs.overall_score END)                               AS amd_score
            FROM forecast_scores fs
            JOIN tafs t ON fs.taf_id = t.id
            WHERE fs.airport_icao = :icao
        """), {"icao": icao}).fetchone()

    if not ap and (agg is None or agg.cnt == 0):
        raise HTTPException(404, f"Airport {icao} not found or has no scored observations")

    total       = amd_rows.total or 0
    amd_count   = int(amd_rows.amd_count or 0)
    cor_count   = int(amd_rows.cor_count or 0)
    amd_pct     = round(amd_count / total * 100, 1) if total else 0.0

    return AirportDetail(
        icao      =icao,
        name      =ap_name,
        lat       =ap_lat,
        lon       =ap_lon,
        summary   =_summary_from_rows(agg),
        amendments=AmendmentStats(
            total_tafs       =total,
            amendment_count  =amd_count,
            correction_count =cor_count,
            amendment_pct    =amd_pct,
            original_score   =_round(amd_rows.orig_score),
            amendment_score  =_round(amd_rows.amd_score),
        ),
    )


# ── /airport/{icao}/by-hour ─────────────────────────────────────────────────

@app.get("/airport/{icao}/by-hour", response_model=list[HourBucket])
def airport_by_hour(
    icao:     str,
    max_hour: int = Query(24, ge=1, le=48, description="Maximum forecast-hour offset to return"),
):
    """
    Accuracy broken down by integer forecast-hour bucket.

    Each bucket covers offsets ``[hour, hour+1)``.  The chart shows how
    accuracy degrades from +1 h (freshest forecast) to +24 h.
    """
    icao = icao.upper()
    with get_session() as session:
        # Run as raw SQL: text() expressions can't be labelled in SQLAlchemy
        # ORM queries, so we go through session.execute() for this one.
        # CAST(… AS INTEGER) truncates toward zero — hour bucket 1 = [1.0, 2.0).
        rows = session.execute(
            text("""
                SELECT
                    CAST(forecast_hour_offset AS INTEGER) AS hour_raw,
                    COUNT(*)                              AS cnt,
                    AVG(overall_score)                    AS overall,
                    AVG(ceiling_coverage_score)           AS ceil_cov,
                    AVG(ceiling_altitude_score)           AS ceil_alt,
                    AVG(visibility_score)                 AS visibility,
                    AVG(wind_speed_score)                 AS wind_speed,
                    AVG(wind_dir_score)                   AS wind_dir
                FROM forecast_scores
                WHERE airport_icao         = :icao
                  AND forecast_hour_offset >= 0
                  AND forecast_hour_offset <  :max_hour
                GROUP BY CAST(forecast_hour_offset AS INTEGER)
                ORDER BY CAST(forecast_hour_offset AS INTEGER)
            """),
            {"icao": icao, "max_hour": max_hour},
        ).fetchall()

    if not rows:
        raise HTTPException(404, f"No scored observations for {icao}")

    return [
        HourBucket(
            hour                   =int(r.hour_raw),
            count                  =r.cnt,
            overall_score          =_round(r.overall),
            ceiling_coverage_score =_round(r.ceil_cov),
            ceiling_altitude_score =_round(r.ceil_alt),
            visibility_score       =_round(r.visibility),
            wind_speed_score       =_round(r.wind_speed),
            wind_dir_score         =_round(r.wind_dir),
        )
        for r in rows
    ]


# ── /airport/{icao}/recent ──────────────────────────────────────────────────

@app.get("/airport/{icao}/recent", response_model=list[RecentObservation])
def airport_recent(
    icao:  str,
    limit: int = Query(48, ge=1, le=200, description="Max observations to return"),
):
    """
    Most recent scored observations for one airport, newest first.

    Useful for a detail table showing raw forecast vs. observed comparisons.
    """
    icao = icao.upper()
    with get_session() as session:
        rows = (
            session.query(
                METAR.observation_time,
                METAR.flight_category,
                ForecastScore.forecast_hour_offset,
                ForecastScore.overall_score,
                ForecastScore.ceiling_coverage_score,
                ForecastScore.ceiling_altitude_score,
                ForecastScore.visibility_score,
                ForecastScore.wind_speed_score,
                ForecastScore.wind_dir_score,
                ForecastScore.tempo_active,
            )
            .join(ForecastScore, METAR.id == ForecastScore.metar_id)
            .filter(ForecastScore.airport_icao == icao)
            .order_by(METAR.observation_time.desc())
            .limit(limit)
            .all()
        )

    if not rows:
        raise HTTPException(404, f"No scored observations for {icao}")

    return [
        RecentObservation(
            observation_time       =r.observation_time,
            forecast_hour_offset   =round(r.forecast_hour_offset, 2),
            flight_category        =r.flight_category,
            overall_score          =_round(r.overall_score),
            ceiling_coverage_score =_round(r.ceiling_coverage_score),
            ceiling_altitude_score =_round(r.ceiling_altitude_score),
            visibility_score       =_round(r.visibility_score),
            wind_speed_score       =_round(r.wind_speed_score),
            wind_dir_score         =_round(r.wind_dir_score),
            tempo_active           =bool(r.tempo_active),
        )
        for r in rows
    ]


# ── /map-data ───────────────────────────────────────────────────────────────

@app.get("/map-data")
def map_data(min_obs: int = Query(1, ge=1)):
    """
    Return all airports with scored observations for map rendering.
    Reads from airport_stats for instant response.
    """
    cache_key = f"map-data:{min_obs}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    with get_session() as session:
        pairs = (
            session.query(AirportStats, Airport)
            .join(Airport, Airport.icao == AirportStats.airport_icao)
            .filter(
                AirportStats.score_count >= min_obs,
                Airport.lat.isnot(None),
                Airport.lon.isnot(None),
            )
            .all()
        )
        result = [
            {
                "icao":              airport.icao,
                "name":              airport.name,
                "lat":               airport.lat,
                "lon":               airport.lon,
                "observation_count": stats.score_count,
                "overall_score":     _round(
                    stats.overall_sum / stats.overall_count
                    if stats.overall_count else None
                ),
            }
            for stats, airport in pairs
        ]

    _cache_set(cache_key, result)
    return result


# ── /airport/{icao}/snapshot ────────────────────────────────────────────────

@app.get("/airport/{icao}/snapshot")
def airport_snapshot(icao: str):
    """
    Return a side-by-side comparison of the most recent stored METAR against
    the aligned TAF forecast conditions at that observation time.

    Used to show the user a concrete, current example of how scoring works.
    """
    from sqlalchemy.orm import joinedload
    from scoring import find_best_taf, resolve_taf_conditions_at_time, score_metar_vs_taf, _iso

    icao = icao.upper()

    with get_session() as session:
        recent_metar = (
            session.query(METAR)
            .filter_by(airport_icao=icao)
            .order_by(METAR.observation_time.desc())
            .first()
        )
        if not recent_metar:
            raise HTTPException(404, f"No METAR data for {icao}")

        metar_dict = _metar_orm_to_dict(recent_metar)
        metar_raw  = recent_metar.raw_text

        db_tafs = (
            session.query(TAF)
            .options(joinedload(TAF.periods))
            .filter_by(airport_icao=icao)
            .all()
        )
        taf_dicts = [_taf_orm_to_dict(t) for t in db_tafs]

    if not taf_dicts:
        raise HTTPException(404, f"No TAF data for {icao}")

    obs_time = _iso(metar_dict["observation_time"])
    best_taf  = find_best_taf(taf_dicts, obs_time)
    if best_taf is None:
        raise HTTPException(404, f"No TAF covers the most recent METAR for {icao}")

    taf_from = _iso(best_taf["valid_from"])
    taf_to   = _iso(best_taf["valid_to"])
    base_cond, _ = resolve_taf_conditions_at_time(
        best_taf["periods"], obs_time, taf_from, taf_to
    )
    if base_cond is None:
        raise HTTPException(404, f"Could not align METAR to TAF for {icao}")

    score = score_metar_vs_taf(metar_dict, best_taf, best_taf["periods"]) or {}
    delta_h = (obs_time - taf_from).total_seconds() / 3600.0

    return {
        "observation_time":    metar_dict["observation_time"],
        "taf_issue_time":      best_taf["issue_time"],
        "forecast_hour_offset": round(delta_h, 1),
        "metar_raw":           metar_raw,
        "taf_raw":             best_taf["raw_text"],
        "observed": {
            "flight_category":   metar_dict.get("flight_category"),
            "ceiling_ft":        metar_dict.get("ceiling_ft"),
            "ceiling_coverage":  metar_dict.get("ceiling_coverage"),
            "visibility_sm":     metar_dict.get("visibility_sm"),
            "wind_dir":          metar_dict.get("wind_dir"),
            "wind_variable":     metar_dict.get("wind_variable"),
            "wind_speed":        metar_dict.get("wind_speed"),
            "wind_gust":         metar_dict.get("wind_gust"),
            "weather_phenomena": metar_dict.get("weather_phenomena") or [],
        },
        "forecast": {
            "ceiling_ft":        base_cond.get("ceiling_ft"),
            "ceiling_coverage":  base_cond.get("ceiling_coverage"),
            "visibility_sm":     base_cond.get("visibility_sm"),
            "visibility_gt":     base_cond.get("visibility_gt"),
            "wind_dir":          base_cond.get("wind_dir"),
            "wind_variable":     base_cond.get("wind_variable"),
            "wind_speed":        base_cond.get("wind_speed"),
            "wind_gust":         base_cond.get("wind_gust"),
            "weather_phenomena": base_cond.get("weather_phenomena") or [],
        },
        "scores": {
            "ceiling_coverage_score": _round(score.get("ceiling_coverage_score")),
            "ceiling_altitude_score": _round(score.get("ceiling_altitude_score")),
            "visibility_score":       _round(score.get("visibility_score")),
            "wind_speed_score":       _round(score.get("wind_speed_score")),
            "wind_dir_score":         _round(score.get("wind_dir_score")),
            "overall_score":          _round(score.get("overall_score")),
        },
    }


# ── Persistent DB cache helpers ───────────────────────────────────────────────

_LEADERBOARD_TTL = 1800  # seconds (30 minutes)

# In-memory layer (avoids DB round-trip within the TTL window)
_mem_cache: dict = {}


def _cache_get(key: str):
    """Return cached data if still fresh (checks memory first, then DB)."""
    mem = _mem_cache.get(key)
    if mem and time.time() - mem["ts"] < _LEADERBOARD_TTL:
        return mem["data"]

    # Try DB
    with get_session() as session:
        row = session.query(ApiCache).filter(ApiCache.key == key).first()
        if row:
            import datetime as _dt
            computed = _dt.datetime.fromisoformat(row.computed_at).timestamp()
            if time.time() - computed < _LEADERBOARD_TTL:
                _mem_cache[key] = {"ts": computed, "data": row.data}
                return row.data
    return None


def _cache_set(key: str, data) -> None:
    """Write to both memory and DB cache."""
    import datetime as _dt
    import json as _json
    from pydantic import BaseModel as _BM
    now_iso = _dt.datetime.utcnow().isoformat() + "Z"
    # Serialize Pydantic models to plain dicts for JSON storage
    if isinstance(data, list) and data and isinstance(data[0], _BM):
        serializable = [item.model_dump() for item in data]
    elif isinstance(data, _BM):
        serializable = data.model_dump()
    else:
        serializable = data
    _mem_cache[key] = {"ts": time.time(), "data": data}
    with get_session() as session:
        existing = session.query(ApiCache).filter(ApiCache.key == key).first()
        if existing:
            existing.data = serializable
            existing.computed_at = now_iso
        else:
            session.add(ApiCache(key=key, data=serializable, computed_at=now_iso))


def _cache_clear_prefix(prefix: str) -> None:
    """Invalidate all keys starting with prefix (memory + DB)."""
    for k in list(_mem_cache.keys()):
        if k.startswith(prefix):
            del _mem_cache[k]
    with get_session() as session:
        session.query(ApiCache).filter(ApiCache.key.like(f"{prefix}%")).delete(synchronize_session=False)


# ── /leaderboard ────────────────────────────────────────────────────────────

def _leaderboard_cache_key(**kwargs) -> str:
    return "leaderboard:" + str(sorted(kwargs.items()))


@app.get("/leaderboard", response_model=list[LeaderboardEntry])
def leaderboard(
    sort_by:        str = Query("overall_score",
                               description="Column to sort by: overall_score | ceiling_score | "
                                           "visibility_score | wind_speed_score | wind_dir_score"),
    min_obs:        int = Query(5, ge=1, description="Minimum observations required for inclusion"),
    limit:          int = Query(1000, ge=1, le=1000),
    state:          Optional[str] = Query(None, description="Filter by US state abbreviation, e.g. IL"),
    military:       bool = Query(False, description="If true, return only military/joint-use stations"),
    wfo:            Optional[str] = Query(None, description="Filter by NWS WFO identifier, e.g. LOT"),
    climate_region: Optional[str] = Query(None, description="Filter by NOAA climate region"),
):
    """
    Ranked leaderboard of all airports with sufficient scored observations.

    ``sort_by`` must be one of the score column names; any other value falls
    back to ``overall_score``.
    """
    cache_key = _leaderboard_cache_key(
        sort_by=sort_by, min_obs=min_obs, limit=limit,
        state=state, military=military, wfo=wfo, climate_region=climate_region,
    )
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    def _avg(total, count):
        return (total / count) if count else None

    # Map sort_by to (attr_sum, attr_count, sort_ascending)
    _stats_sort_map = {
        "overall_score":          ("overall_sum",              "overall_count",            False),
        "ceiling_coverage_score": ("ceiling_coverage_sum",     "ceiling_coverage_count",   False),
        "ceiling_altitude_score": ("ceiling_altitude_sum",     "ceiling_altitude_count",   False),
        "visibility_score":       ("visibility_sum",           "visibility_count",         False),
        "wind_speed_score":       ("wind_speed_sum",           "wind_speed_count",         False),
        "wind_dir_score":         ("wind_dir_sum",             "wind_dir_count",           False),
        "ceiling_coverage_diff":  ("ceiling_coverage_diff_sum","ceiling_coverage_diff_count", True),
        "ceiling_altitude_diff":  ("ceiling_altitude_diff_sum","ceiling_altitude_diff_count", True),
        "visibility_diff":        ("visibility_diff_sum",      "visibility_diff_count",    True),
        "wind_speed_diff":        ("wind_speed_diff_sum",      "wind_speed_diff_count",    True),
        "wind_dir_diff":          ("wind_dir_diff_sum",        "wind_dir_diff_count",      True),
    }
    sum_attr, cnt_attr, sort_asc = _stats_sort_map.get(sort_by, _stats_sort_map["overall_score"])

    with get_session() as session:
        q = (
            session.query(AirportStats, Airport)
            .join(Airport, Airport.icao == AirportStats.airport_icao)
            .filter(AirportStats.score_count >= min_obs)
        )
        if state:
            q = q.filter(Airport.state == state.upper())
        if military:
            q = q.filter(Airport.icao.in_(MILITARY_STATIONS))
        if wfo:
            q = q.filter(Airport.wfo == wfo.upper())
        if climate_region:
            q = q.filter(Airport.climate_region == climate_region)

        # Materialize all values while session is open to avoid DetachedInstanceError
        entries = []
        for stats, airport in q.all():
            sort_val = _avg(getattr(stats, sum_attr), getattr(stats, cnt_attr))
            amd_pct  = _avg(stats.amendment_count, stats.taf_count) if stats.taf_count else None
            entries.append((sort_val, dict(
                icao                   =airport.icao,
                name                   =airport.name,
                state                  =airport.state,
                wfo                    =airport.wfo,
                climate_region         =airport.climate_region,
                lat                    =airport.lat,
                lon                    =airport.lon,
                observation_count       =stats.score_count,
                overall_score          =_round(_avg(stats.overall_sum, stats.overall_count)),
                ceiling_coverage_score =_round(_avg(stats.ceiling_coverage_sum, stats.ceiling_coverage_count)),
                ceiling_altitude_score =_round(_avg(stats.ceiling_altitude_sum, stats.ceiling_altitude_count)),
                visibility_score       =_round(_avg(stats.visibility_sum, stats.visibility_count)),
                wind_speed_score       =_round(_avg(stats.wind_speed_sum, stats.wind_speed_count)),
                wind_dir_score         =_round(_avg(stats.wind_dir_sum, stats.wind_dir_count)),
                amendment_pct          =_round(amd_pct),
                ceiling_coverage_diff  =_round(_avg(stats.ceiling_coverage_diff_sum, stats.ceiling_coverage_diff_count)),
                ceiling_altitude_diff  =_round(_avg(stats.ceiling_altitude_diff_sum, stats.ceiling_altitude_diff_count)),
                visibility_diff        =_round(_avg(stats.visibility_diff_sum, stats.visibility_diff_count)),
                wind_speed_diff        =_round(_avg(stats.wind_speed_diff_sum, stats.wind_speed_diff_count)),
                wind_dir_diff          =_round(_avg(stats.wind_dir_diff_sum, stats.wind_dir_diff_count)),
            )))

    entries.sort(key=lambda x: (x[0] is None, x[0] if x[0] is not None else 0), reverse=not sort_asc)
    entries = entries[:limit]

    result = [
        LeaderboardEntry(
            rank        =i + 1,
            is_military =e["icao"] in MILITARY_STATIONS,
            **{k: v for k, v in e.items()},
        )
        for i, (_, e) in enumerate(entries)
    ]

    _cache_set(cache_key, result)
    return result


# ── /ingest ─────────────────────────────────────────────────────────────────

# Track airports currently being ingested to avoid duplicate concurrent runs
_ingesting: set[str] = set()


def _run_ingest(icao: str) -> None:
    """Background task wrapper that clears the in-progress flag when done."""
    try:
        stats = process_station(icao)
        logger.info("Ingest complete for %s: %s", icao, stats)
        _cache_clear_prefix("leaderboard:")
        _cache_clear_prefix("analytics:")
        _cache_clear_prefix("map-data:")
    except Exception as exc:
        logger.error("Ingest failed for %s: %s", icao, exc)
    finally:
        _ingesting.discard(icao)


@app.post("/ingest/{icao}", response_model=IngestResponse)
def ingest_airport(icao: str, background_tasks: BackgroundTasks, _=Depends(_require_ingest_key)):
    """
    Trigger a background fetch-and-score run for one airport.

    Returns immediately with ``status="queued"`` or ``status="skipped"``
    if a run is already in progress for that airport.
    """
    icao = icao.upper()
    if len(icao) != 4:
        raise HTTPException(400, f"Invalid ICAO code: {icao!r} (must be 4 letters)")

    if icao in _ingesting:
        return IngestResponse(status="skipped", airports=[icao])

    _ingesting.add(icao)
    background_tasks.add_task(_run_ingest, icao)
    return IngestResponse(status="queued", airports=[icao])


# ── /analytics ───────────────────────────────────────────────────────────────

@app.get("/analytics")
def analytics():
    """
    Pre-aggregated data for the Analytics page.

    Returns a slim per-airport array (only fields needed for charts/regression)
    plus server-side aggregates for region scores and score distribution.
    Reads from airport_stats for instant response.
    """
    cached = _cache_get("analytics:airports")
    if cached is not None:
        return cached

    def _avg(s, c):
        return (s / c) if c else None

    with get_session() as session:
        pairs = (
            session.query(AirportStats, Airport)
            .join(Airport, Airport.icao == AirportStats.airport_icao)
            .all()
        )
        airports = []
        for stats, ap in pairs:
            amd_pct = _avg(stats.amendment_count, stats.taf_count)
            airports.append({
                "icao":                   ap.icao,
                "lat":                    ap.lat,
                "lon":                    ap.lon,
                "climate_region":         ap.climate_region,
                "wfo":                    ap.wfo,
                "is_military":            ap.icao in MILITARY_STATIONS,
                "observation_count":      stats.score_count,
                "overall_score":          _round(_avg(stats.overall_sum, stats.overall_count), 4),
                "ceiling_coverage_score": _round(_avg(stats.ceiling_coverage_sum, stats.ceiling_coverage_count), 4),
                "ceiling_altitude_score": _round(_avg(stats.ceiling_altitude_sum, stats.ceiling_altitude_count), 4),
                "visibility_score":       _round(_avg(stats.visibility_sum, stats.visibility_count), 4),
                "wind_speed_score":       _round(_avg(stats.wind_speed_sum, stats.wind_speed_count), 4),
                "wind_dir_score":         _round(_avg(stats.wind_dir_sum, stats.wind_dir_count), 4),
                "amendment_pct":          round(amd_pct * 100, 2) if amd_pct is not None else None,
            })

    result = {"airports": airports}
    _cache_set("analytics:airports", result)
    return result


# ── /analytics/lead-time ─────────────────────────────────────────────────────

@app.get("/analytics/lead-time")
def analytics_lead_time():
    """
    Average TAF accuracy by forecast lead time (hours between TAF issue and observation).
    Returns one row per integer lead hour (0–29), with overall + component scores.
    Reads from lead_time_stats for instant response.
    """
    cached = _cache_get("analytics:lead-time")
    if cached is not None:
        return cached

    def _pct(s, c):
        return round(s / c * 100, 2) if c else None

    with get_session() as session:
        rows = session.query(LeadTimeStats).order_by(LeadTimeStats.lead_hour).all()
        result = [
            {
                "hour":        lt.lead_hour,
                "overall":     _pct(lt.overall_sum, lt.overall_count),
                "ceiling_cov": _pct(lt.ceiling_coverage_sum, lt.ceiling_coverage_count),
                "ceiling_alt": _pct(lt.ceiling_altitude_sum, lt.ceiling_altitude_count),
                "visibility":  _pct(lt.visibility_sum, lt.visibility_count),
                "wind_spd":    _pct(lt.wind_speed_sum, lt.wind_speed_count),
                "wind_dir":    _pct(lt.wind_dir_sum, lt.wind_dir_count),
                "n":           lt.score_count,
            }
            for lt in rows
        ]

    _cache_set("analytics:lead-time", result)
    return result


# ── /analytics/daily-comparisons ─────────────────────────────────────────────

@app.get("/analytics/daily-comparisons")
def analytics_daily_comparisons():
    """Daily count of scored comparisons (forecast_scores rows) by observation date."""
    cached = _cache_get("analytics:daily-comparisons")
    if cached is not None:
        return cached

    with get_session() as session:
        rows = session.query(DailyStats).order_by(DailyStats.date).all()
        result = [{"date": ds.date, "comparisons": ds.score_count} for ds in rows]

    _cache_set("analytics:daily-comparisons", result)
    return result


@app.post("/ingest/batch", response_model=IngestResponse)
def ingest_batch(
    background_tasks: BackgroundTasks,
    airports: Optional[list[str]] = None,
    _=Depends(_require_ingest_key),
):
    """
    Trigger background ingest for a list of airports.
    If ``airports`` is omitted, queues all bundled US TAF stations.
    """
    targets = [a.upper() for a in (airports or US_TAF_STATIONS)]
    queued = []
    for icao in targets:
        if icao not in _ingesting:
            _ingesting.add(icao)
            background_tasks.add_task(_run_ingest, icao)
            queued.append(icao)

    return IngestResponse(status="queued", airports=queued)


# ---------------------------------------------------------------------------
# Admin: chunked SQL import (temporary — remove after backfill complete)
# ---------------------------------------------------------------------------
import threading, gzip as _gzip, sqlite3 as _sqlite3, pathlib as _pathlib

_import_status: dict = {"running": False, "done": 0, "total_chunks": 0, "error": None}

def _run_sql_import(sql_path: str, chunk_size: int = 5000):
    global _import_status
    _import_status = {"running": True, "done": 0, "total_chunks": 0, "error": None}
    db_path = os.environ.get("TAF_DB_PATH", "/data/taf_accuracy.db")
    try:
        open_fn = _gzip.open if sql_path.endswith(".gz") else open
        mode    = "rt" if sql_path.endswith(".gz") else "r"
        con = _sqlite3.connect(db_path, timeout=120)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        con.execute("PRAGMA foreign_keys=OFF")
        con.execute("BEGIN")
        chunk_count = 0
        buf = 0
        stmt_parts: list = []
        with open_fn(sql_path, mode) as fh:
            for line in fh:
                stripped = line.strip()
                if not stripped or stripped.startswith("--"):
                    continue
                if stripped in ("BEGIN;", "BEGIN", "COMMIT;", "COMMIT"):
                    continue
                if stripped.startswith("PRAGMA"):
                    continue
                # Accumulate lines until we have a complete statement (ends with ;)
                stmt_parts.append(line.rstrip("\n"))
                stmt = "\n".join(stmt_parts)
                if not stmt.rstrip().endswith(";"):
                    continue  # incomplete — keep accumulating
                stmt_parts = []
                stmt = stmt.strip()
                if not stmt.upper().startswith("INSERT"):
                    continue
                try:
                    con.execute(stmt)
                except _sqlite3.IntegrityError:
                    pass
                buf += 1
                if buf >= chunk_size:
                    con.execute("COMMIT")
                    chunk_count += 1
                    _import_status["total_chunks"] = chunk_count
                    con.execute("BEGIN")
                    buf = 0
        con.execute("COMMIT")
        chunk_count += 1
        _import_status["total_chunks"] = chunk_count
        con.close()
        _import_status["done"] = chunk_count
    except Exception as exc:
        _import_status["error"] = str(exc)
    finally:
        _import_status["running"] = False


@app.post("/admin/upload-sql")
async def admin_upload_sql(request: Request, filename: str = "import.sql.gz"):
    """Accept a gzipped SQL file upload and save to /data."""
    dest = _pathlib.Path("/data") / _pathlib.Path(filename).name
    with open(dest, "wb") as f:
        async for chunk in request.stream():
            f.write(chunk)
    return {"status": "uploaded", "path": str(dest), "bytes": dest.stat().st_size}


@app.post("/admin/import-sql")
def admin_import_sql(sql_file: str = "/data/2026-06.sql.gz", chunk_size: int = 5000):
    """Start a background SQL import from a file already on the server."""
    if _import_status.get("running"):
        return {"status": "already_running", **_import_status}
    if not _pathlib.Path(sql_file).exists():
        raise HTTPException(404, f"File not found: {sql_file}")
    t = threading.Thread(target=_run_sql_import, args=(sql_file, chunk_size), daemon=True)
    t.start()
    return {"status": "started", "file": sql_file}


@app.get("/admin/import-status")
def admin_import_status():
    """Check status of in-progress SQL import."""
    return _import_status


_stats_backfill_status: dict = {"running": False, "done": 0, "error": None}

def _run_stats_backfill():
    """Populate airport_stats from all existing forecast_scores. One-time operation."""
    global _stats_backfill_status
    _stats_backfill_status = {"running": True, "done": 0, "error": None}
    try:
        with get_session() as session:
            session.execute(text("DELETE FROM airport_stats"))
            rows = session.execute(text("""
                SELECT
                    airport_icao,
                    COUNT(*) AS score_count,
                    SUM(CASE WHEN overall_score IS NOT NULL THEN overall_score ELSE 0 END) AS overall_sum,
                    SUM(CASE WHEN overall_score IS NOT NULL THEN 1 ELSE 0 END) AS overall_count,
                    SUM(CASE WHEN ceiling_coverage_score IS NOT NULL THEN ceiling_coverage_score ELSE 0 END) AS ceiling_coverage_sum,
                    SUM(CASE WHEN ceiling_coverage_score IS NOT NULL THEN 1 ELSE 0 END) AS ceiling_coverage_count,
                    SUM(CASE WHEN ceiling_altitude_score IS NOT NULL THEN ceiling_altitude_score ELSE 0 END) AS ceiling_altitude_sum,
                    SUM(CASE WHEN ceiling_altitude_score IS NOT NULL THEN 1 ELSE 0 END) AS ceiling_altitude_count,
                    SUM(CASE WHEN visibility_score IS NOT NULL THEN visibility_score ELSE 0 END) AS visibility_sum,
                    SUM(CASE WHEN visibility_score IS NOT NULL THEN 1 ELSE 0 END) AS visibility_count,
                    SUM(CASE WHEN wind_speed_score IS NOT NULL THEN wind_speed_score ELSE 0 END) AS wind_speed_sum,
                    SUM(CASE WHEN wind_speed_score IS NOT NULL THEN 1 ELSE 0 END) AS wind_speed_count,
                    SUM(CASE WHEN wind_dir_score IS NOT NULL THEN wind_dir_score ELSE 0 END) AS wind_dir_sum,
                    SUM(CASE WHEN wind_dir_score IS NOT NULL THEN 1 ELSE 0 END) AS wind_dir_count,
                    SUM(CASE WHEN ceiling_coverage_diff IS NOT NULL THEN ceiling_coverage_diff ELSE 0 END) AS ceiling_coverage_diff_sum,
                    SUM(CASE WHEN ceiling_coverage_diff IS NOT NULL THEN 1 ELSE 0 END) AS ceiling_coverage_diff_count,
                    SUM(CASE WHEN ceiling_altitude_diff IS NOT NULL THEN ceiling_altitude_diff ELSE 0 END) AS ceiling_altitude_diff_sum,
                    SUM(CASE WHEN ceiling_altitude_diff IS NOT NULL THEN 1 ELSE 0 END) AS ceiling_altitude_diff_count,
                    SUM(CASE WHEN visibility_diff IS NOT NULL THEN visibility_diff ELSE 0 END) AS visibility_diff_sum,
                    SUM(CASE WHEN visibility_diff IS NOT NULL THEN 1 ELSE 0 END) AS visibility_diff_count,
                    SUM(CASE WHEN wind_speed_diff IS NOT NULL THEN wind_speed_diff ELSE 0 END) AS wind_speed_diff_sum,
                    SUM(CASE WHEN wind_speed_diff IS NOT NULL THEN 1 ELSE 0 END) AS wind_speed_diff_count,
                    SUM(CASE WHEN wind_dir_diff IS NOT NULL THEN wind_dir_diff ELSE 0 END) AS wind_dir_diff_sum,
                    SUM(CASE WHEN wind_dir_diff IS NOT NULL THEN 1 ELSE 0 END) AS wind_dir_diff_count
                FROM forecast_scores
                GROUP BY airport_icao
            """)).fetchall()
            amd_rows = session.execute(text("""
                SELECT airport_icao,
                       COUNT(*) AS taf_count,
                       SUM(is_amendment) AS amendment_count
                FROM tafs GROUP BY airport_icao
            """)).fetchall()
            amd = {r.airport_icao: (r.taf_count, r.amendment_count) for r in amd_rows}
            for r in rows:
                tc, ac = amd.get(r.airport_icao, (0, 0))
                session.execute(text("""
                    INSERT OR REPLACE INTO airport_stats (
                        airport_icao, score_count,
                        overall_sum, overall_count,
                        ceiling_coverage_sum, ceiling_coverage_count,
                        ceiling_altitude_sum, ceiling_altitude_count,
                        visibility_sum, visibility_count,
                        wind_speed_sum, wind_speed_count,
                        wind_dir_sum, wind_dir_count,
                        ceiling_coverage_diff_sum, ceiling_coverage_diff_count,
                        ceiling_altitude_diff_sum, ceiling_altitude_diff_count,
                        visibility_diff_sum, visibility_diff_count,
                        wind_speed_diff_sum, wind_speed_diff_count,
                        wind_dir_diff_sum, wind_dir_diff_count,
                        taf_count, amendment_count
                    ) VALUES (
                        :icao, :sc,
                        :os, :oc, :ccs, :ccc, :cas, :cac, :vs, :vc, :wss, :wsc, :wds, :wdc,
                        :ccds, :ccdc, :cads, :cadc, :vds, :vdc, :wsds, :wsdc, :wdds, :wddc,
                        :tc, :ac
                    )
                """), dict(
                    icao=r.airport_icao, sc=r.score_count,
                    os=r.overall_sum, oc=r.overall_count,
                    ccs=r.ceiling_coverage_sum, ccc=r.ceiling_coverage_count,
                    cas=r.ceiling_altitude_sum, cac=r.ceiling_altitude_count,
                    vs=r.visibility_sum, vc=r.visibility_count,
                    wss=r.wind_speed_sum, wsc=r.wind_speed_count,
                    wds=r.wind_dir_sum, wdc=r.wind_dir_count,
                    ccds=r.ceiling_coverage_diff_sum, ccdc=r.ceiling_coverage_diff_count,
                    cads=r.ceiling_altitude_diff_sum, cadc=r.ceiling_altitude_diff_count,
                    vds=r.visibility_diff_sum, vdc=r.visibility_diff_count,
                    wsds=r.wind_speed_diff_sum, wsdc=r.wind_speed_diff_count,
                    wdds=r.wind_dir_diff_sum, wddc=r.wind_dir_diff_count,
                    tc=tc, ac=ac,
                ))
            _stats_backfill_status["done"] = len(rows)
    except Exception as exc:
        _stats_backfill_status["error"] = str(exc)
    finally:
        _stats_backfill_status["running"] = False


@app.post("/admin/backfill-stats")
def admin_backfill_stats():
    """Rebuild airport_stats from all existing forecast_scores. Safe to re-run."""
    if _stats_backfill_status.get("running"):
        return {"status": "already_running", **_stats_backfill_status}
    t = threading.Thread(target=_run_stats_backfill, daemon=True)
    t.start()
    return {"status": "started"}


@app.get("/admin/backfill-stats-status")
def admin_backfill_stats_status():
    return _stats_backfill_status


_lead_time_backfill_status: dict = {"running": False, "done": 0, "error": None}

def _run_lead_time_backfill():
    global _lead_time_backfill_status
    _lead_time_backfill_status = {"running": True, "done": 0, "error": None}
    try:
        with get_session() as session:
            session.execute(text("DELETE FROM lead_time_stats"))
            rows = session.execute(text("""
                SELECT
                    CAST(forecast_hour_offset AS INTEGER) AS lead_hour,
                    COUNT(*) AS score_count,
                    SUM(CASE WHEN overall_score IS NOT NULL THEN overall_score ELSE 0 END) AS overall_sum,
                    SUM(CASE WHEN overall_score IS NOT NULL THEN 1 ELSE 0 END) AS overall_count,
                    SUM(CASE WHEN ceiling_coverage_score IS NOT NULL THEN ceiling_coverage_score ELSE 0 END) AS ceiling_coverage_sum,
                    SUM(CASE WHEN ceiling_coverage_score IS NOT NULL THEN 1 ELSE 0 END) AS ceiling_coverage_count,
                    SUM(CASE WHEN ceiling_altitude_score IS NOT NULL THEN ceiling_altitude_score ELSE 0 END) AS ceiling_altitude_sum,
                    SUM(CASE WHEN ceiling_altitude_score IS NOT NULL THEN 1 ELSE 0 END) AS ceiling_altitude_count,
                    SUM(CASE WHEN visibility_score IS NOT NULL THEN visibility_score ELSE 0 END) AS visibility_sum,
                    SUM(CASE WHEN visibility_score IS NOT NULL THEN 1 ELSE 0 END) AS visibility_count,
                    SUM(CASE WHEN wind_speed_score IS NOT NULL THEN wind_speed_score ELSE 0 END) AS wind_speed_sum,
                    SUM(CASE WHEN wind_speed_score IS NOT NULL THEN 1 ELSE 0 END) AS wind_speed_count,
                    SUM(CASE WHEN wind_dir_score IS NOT NULL THEN wind_dir_score ELSE 0 END) AS wind_dir_sum,
                    SUM(CASE WHEN wind_dir_score IS NOT NULL THEN 1 ELSE 0 END) AS wind_dir_count
                FROM forecast_scores
                WHERE CAST(forecast_hour_offset AS INTEGER) BETWEEN 0 AND 29
                GROUP BY lead_hour
                ORDER BY lead_hour
            """)).fetchall()
            for r in rows:
                session.execute(text("""
                    INSERT INTO lead_time_stats (
                        lead_hour, score_count,
                        overall_sum, overall_count,
                        ceiling_coverage_sum, ceiling_coverage_count,
                        ceiling_altitude_sum, ceiling_altitude_count,
                        visibility_sum, visibility_count,
                        wind_speed_sum, wind_speed_count,
                        wind_dir_sum, wind_dir_count
                    ) VALUES (
                        :lh, :sc, :os, :oc, :ccs, :ccc, :cas, :cac,
                        :vs, :vc, :wss, :wsc, :wds, :wdc
                    )
                """), dict(
                    lh=r.lead_hour, sc=r.score_count,
                    os=r.overall_sum, oc=r.overall_count,
                    ccs=r.ceiling_coverage_sum, ccc=r.ceiling_coverage_count,
                    cas=r.ceiling_altitude_sum, cac=r.ceiling_altitude_count,
                    vs=r.visibility_sum, vc=r.visibility_count,
                    wss=r.wind_speed_sum, wsc=r.wind_speed_count,
                    wds=r.wind_dir_sum, wdc=r.wind_dir_count,
                ))
            _lead_time_backfill_status["done"] = len(rows)
    except Exception as exc:
        _lead_time_backfill_status["error"] = str(exc)
    finally:
        _lead_time_backfill_status["running"] = False


@app.post("/admin/backfill-lead-time-stats")
def admin_backfill_lead_time_stats():
    """Rebuild lead_time_stats from all existing forecast_scores. Safe to re-run."""
    if _lead_time_backfill_status.get("running"):
        return {"status": "already_running", **_lead_time_backfill_status}
    t = threading.Thread(target=_run_lead_time_backfill, daemon=True)
    t.start()
    return {"status": "started"}


@app.get("/admin/backfill-lead-time-stats-status")
def admin_backfill_lead_time_stats_status():
    return _lead_time_backfill_status


_daily_backfill_status: dict = {"running": False, "done": 0, "error": None}

def _run_daily_backfill():
    global _daily_backfill_status
    _daily_backfill_status = {"running": True, "done": 0, "error": None}
    try:
        with get_session() as session:
            session.execute(text("DELETE FROM daily_stats"))
            rows = session.execute(text("""
                SELECT
                    substr(m.observation_time, 1, 10) AS date,
                    COUNT(*) AS score_count
                FROM forecast_scores fs
                JOIN metars m ON fs.metar_id = m.id
                GROUP BY date
                ORDER BY date
            """)).fetchall()
            for r in rows:
                session.execute(text(
                    "INSERT INTO daily_stats (date, score_count) VALUES (:d, :sc)"
                ), {"d": r.date, "sc": r.score_count})
            _daily_backfill_status["done"] = len(rows)
    except Exception as exc:
        _daily_backfill_status["error"] = str(exc)
    finally:
        _daily_backfill_status["running"] = False


@app.post("/admin/backfill-daily-stats")
def admin_backfill_daily_stats():
    """Rebuild daily_stats from all existing forecast_scores. Safe to re-run."""
    if _daily_backfill_status.get("running"):
        return {"status": "already_running", **_daily_backfill_status}
    t = threading.Thread(target=_run_daily_backfill, daemon=True)
    t.start()
    return {"status": "started"}


@app.get("/admin/backfill-daily-stats-status")
def admin_backfill_daily_stats_status():
    return _daily_backfill_status


@app.post("/admin/clear-cache")
def admin_clear_cache(_=Depends(_require_ingest_key)):
    """Invalidate all in-memory and DB caches (leaderboard + analytics)."""
    _cache_clear_prefix("leaderboard:")
    _cache_clear_prefix("analytics:")
    _cache_clear_prefix("map-data:")
    return {"status": "cleared"}


@app.get("/admin/metar-diag")
def admin_metar_diag(start: str = "2026-05-15", end: str = "2026-06-01"):
    """Diagnostic: METAR counts per day with TZ-suffix breakdown."""
    with get_session() as session:
        rows = session.execute(text("""
            SELECT
                substr(observation_time, 1, 10)                                    AS d,
                COUNT(*)                                                           AS total,
                SUM(CASE WHEN observation_time LIKE '%+00:00' THEN 1 ELSE 0 END)   AS tz_count,
                SUM(CASE WHEN observation_time NOT LIKE '%+00:00' THEN 1 ELSE 0 END) AS no_tz_count
            FROM metars
            WHERE substr(observation_time,1,10) >= :start
              AND substr(observation_time,1,10) <  :end
            GROUP BY d ORDER BY d
        """), {"start": start, "end": end}).fetchall()
    return [{"date": r.d, "total": r.total, "tz_suffix": r.tz_count, "no_suffix": r.no_tz_count} for r in rows]


@app.get("/admin/airport-count-by-date")
def admin_airport_count_by_date(date: str = "2026-04-30"):
    """Distinct airports + metar count for one specific date."""
    with get_session() as session:
        row = session.execute(text("""
            SELECT COUNT(DISTINCT airport_icao) AS airports, COUNT(*) AS metars
            FROM metars
            WHERE substr(observation_time,1,10) = :date
        """), {"date": date}).fetchone()
    return {"date": date, "airports": row.airports, "metars": row.metars,
            "avg_per_airport": round(row.metars / row.airports, 1) if row.airports else None}


@app.get("/admin/metar-sample")
def admin_metar_sample(date: str = "2026-05-20", airport: str = "KORD"):
    """Sample observation_times for one airport on one day, to inspect format."""
    with get_session() as session:
        rows = session.execute(text("""
            SELECT observation_time, raw_text
            FROM metars
            WHERE airport_icao = :icao
              AND substr(observation_time,1,10) = :date
            ORDER BY observation_time
        """), {"icao": airport, "date": date}).fetchall()
    return [{"observation_time": r.observation_time, "raw": r.raw_text[:60]} for r in rows]
