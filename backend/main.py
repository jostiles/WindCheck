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
from typing import Optional

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import func, text

from database import get_session, init_db
from ingest import process_station, US_TAF_STATIONS, _taf_orm_to_dict, _metar_orm_to_dict
from models import Airport, ForecastScore, METAR, TAF

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


@app.on_event("startup")
def _startup() -> None:
    init_db()
    logging.basicConfig(level=logging.INFO)


_INGEST_KEY = os.getenv("INGEST_API_KEY", "")

def _require_ingest_key(x_api_key: str = Header(default="")):
    """Dependency that enforces the INGEST_API_KEY on write endpoints."""
    if not _INGEST_KEY:
        return  # key not configured — allow (dev mode)
    if x_api_key != _INGEST_KEY:
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


class AirportDetail(BaseModel):
    icao:    str
    name:    Optional[str]
    lat:     Optional[float]
    lon:     Optional[float]
    summary: ScoreSummary


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
    observation_count:      int
    overall_score:          Optional[float]
    ceiling_coverage_score: Optional[float]
    ceiling_altitude_score: Optional[float]
    visibility_score:       Optional[float]
    wind_speed_score:       Optional[float]
    wind_dir_score:         Optional[float]


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
        func.count(ForecastScore.id)                      .label("cnt"),
        func.avg(ForecastScore.overall_score)             .label("overall"),
        func.avg(ForecastScore.ceiling_coverage_score)    .label("ceil_cov"),
        func.avg(ForecastScore.ceiling_altitude_score)    .label("ceil_alt"),
        func.avg(ForecastScore.visibility_score)          .label("visibility"),
        func.avg(ForecastScore.wind_speed_score)          .label("wind_speed"),
        func.avg(ForecastScore.wind_dir_score)            .label("wind_dir"),
        func.avg(ForecastScore.wx_precision)              .label("wx_prec"),
        func.avg(ForecastScore.wx_recall)                 .label("wx_rec"),
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
        # Read scalar values inside the session so the ORM object
        # doesn't become detached before we access its attributes.
        ap_name = ap.name if ap else None
        ap_lat  = ap.lat  if ap else None
        ap_lon  = ap.lon  if ap else None

        agg = (
            session.query(*_score_agg_cols())
            .filter(ForecastScore.airport_icao == icao)
            .one()
        )

    if not ap and (agg is None or agg.cnt == 0):
        raise HTTPException(404, f"Airport {icao} not found or has no scored observations")

    return AirportDetail(
        icao   =icao,
        name   =ap_name,
        lat    =ap_lat,
        lon    =ap_lon,
        summary=_summary_from_rows(agg),
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
    Includes lat/lon and overall accuracy score.
    """
    with get_session() as session:
        rows = (
            session.query(
                Airport.icao,
                Airport.name,
                Airport.lat,
                Airport.lon,
                func.count(ForecastScore.id).label("cnt"),
                func.avg(ForecastScore.overall_score).label("overall"),
            )
            .join(ForecastScore, Airport.icao == ForecastScore.airport_icao)
            .filter(Airport.lat.isnot(None), Airport.lon.isnot(None))
            .group_by(Airport.icao, Airport.name, Airport.lat, Airport.lon)
            .having(func.count(ForecastScore.id) >= min_obs)
            .all()
        )

    return [
        {
            "icao":              r.icao,
            "name":              r.name,
            "lat":               r.lat,
            "lon":               r.lon,
            "observation_count": r.cnt,
            "overall_score":     _round(r.overall),
        }
        for r in rows
    ]


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


# ── /leaderboard ────────────────────────────────────────────────────────────

@app.get("/leaderboard", response_model=list[LeaderboardEntry])
def leaderboard(
    sort_by:  str = Query("overall_score",
                          description="Column to sort by: overall_score | ceiling_score | "
                                      "visibility_score | wind_speed_score | wind_dir_score"),
    min_obs:  int = Query(5, ge=1, description="Minimum observations required for inclusion"),
    limit:    int = Query(1000, ge=1, le=1000),
    state:    Optional[str] = Query(None, description="Filter by US state abbreviation, e.g. IL"),
):
    """
    Ranked leaderboard of all airports with sufficient scored observations.

    ``sort_by`` must be one of the score column names; any other value falls
    back to ``overall_score``.
    """
    # Whitelist sortable columns
    _sort_map = {
        "overall_score":          func.avg(ForecastScore.overall_score),
        "ceiling_coverage_score": func.avg(ForecastScore.ceiling_coverage_score),
        "ceiling_altitude_score": func.avg(ForecastScore.ceiling_altitude_score),
        "visibility_score":       func.avg(ForecastScore.visibility_score),
        "wind_speed_score":       func.avg(ForecastScore.wind_speed_score),
        "wind_dir_score":         func.avg(ForecastScore.wind_dir_score),
    }
    sort_col = _sort_map.get(sort_by, _sort_map["overall_score"])

    with get_session() as session:
        q = (
            session.query(
                Airport.icao,
                Airport.name,
                Airport.state,
                *_score_agg_cols(),
            )
            .join(ForecastScore, Airport.icao == ForecastScore.airport_icao)
            .group_by(Airport.icao, Airport.name, Airport.state)
            .having(func.count(ForecastScore.id) >= min_obs)
            .order_by(sort_col.desc().nullslast())
            .limit(limit)
        )
        if state:
            q = q.filter(Airport.state == state.upper())
        rows = q.all()

    return [
        LeaderboardEntry(
            rank                   =i + 1,
            icao                   =r.icao,
            name                   =r.name,
            state                  =r.state,
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


# ── /ingest ─────────────────────────────────────────────────────────────────

# Track airports currently being ingested to avoid duplicate concurrent runs
_ingesting: set[str] = set()


def _run_ingest(icao: str) -> None:
    """Background task wrapper that clears the in-progress flag when done."""
    try:
        stats = process_station(icao)
        logger.info("Ingest complete for %s: %s", icao, stats)
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
