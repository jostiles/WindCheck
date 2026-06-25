"""
SQLAlchemy ORM models for the TAF accuracy database.

Schema overview
---------------
  Airport        — static info (ICAO code, name, lat/lon)
  TAF            — one row per issued TAF bulletin
  TAFPeriod      — one row per period group within a TAF
                   (BASE / FM / BECMG / TEMPO / PROB)
  METAR          — one row per decoded METAR observation
  ForecastScore  — one row per (METAR, TAF) pair with per-parameter accuracy scores

Period type semantics
---------------------
  BASE   The main body of the TAF (period_seq = 0).  Conditions apply from
         valid_from until the first FM group (or end of TAF if none).
  FM     "From" group.  Completely replaces *all* prior conditions from its
         start time forward.  Each FM starts a new "base" epoch.
  BECMG  "Becoming".  Specifies a gradual transition from valid_from to
         valid_to.  After valid_to the new conditions persist as part of the
         base until the next FM.  Only the elements explicitly listed in the
         BECMG line change; the rest are inherited from the current FM/BASE.
  TEMPO  "Temporary".  Conditions expected to fluctuate for < half the period
         duration.  Layered on top of the current base; base conditions resume
         after valid_to.
  PROB   Probability group (PROB30 / PROB40).  May combine with TEMPO.
         Conditions are probabilistic and scored separately.
"""

from sqlalchemy import (
    Column, Float, ForeignKey, Index, Integer, JSON,
    String, Text, UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Airport
# ---------------------------------------------------------------------------

class Airport(Base):
    """Static airport/station information."""

    __tablename__ = "airports"

    icao           = Column(String(4), primary_key=True)
    name           = Column(String(200))
    state          = Column(String(2))    # US state abbreviation, e.g. "IL"
    wfo            = Column(String(4))    # NWS Weather Forecast Office, e.g. "LOT"
    climate_region = Column(String(30))   # NOAA climate region, e.g. "Upper Midwest"
    lat            = Column(Float)
    lon            = Column(Float)

    metars = relationship("METAR",         back_populates="airport")
    tafs   = relationship("TAF",           back_populates="airport")
    scores = relationship("ForecastScore", back_populates="airport")

    def __repr__(self) -> str:
        return f"<Airport {self.icao}>"


# ---------------------------------------------------------------------------
# TAF  +  TAFPeriod
# ---------------------------------------------------------------------------

class TAF(Base):
    """One issued TAF bulletin."""

    __tablename__ = "tafs"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    airport_icao   = Column(String(4), ForeignKey("airports.icao"), nullable=False)
    issue_time     = Column(String,    nullable=False)  # stored as ISO-8601 string
    valid_from     = Column(String,    nullable=False)  # ISO-8601
    valid_to       = Column(String,    nullable=False)  # ISO-8601
    raw_text       = Column(Text,      nullable=False)
    is_amendment   = Column(Integer,   default=0)  # 1 if TAF AMD
    is_correction  = Column(Integer,   default=0)  # 1 if TAF COR

    airport = relationship("Airport",    back_populates="tafs")
    periods = relationship("TAFPeriod",  back_populates="taf",
                           cascade="all, delete-orphan",
                           order_by="TAFPeriod.period_seq")
    scores  = relationship("ForecastScore", back_populates="taf")

    __table_args__ = (
        UniqueConstraint("airport_icao", "issue_time", name="uq_taf_airport_issue"),
        Index("ix_taf_airport_valid", "airport_icao", "valid_from", "valid_to"),
    )

    def __repr__(self) -> str:
        return f"<TAF {self.airport_icao} issued={self.issue_time}>"


class TAFPeriod(Base):
    """
    One weather-condition group within a TAF.

    NULL values for wind/visibility/ceiling/weather mean the element was not
    explicitly stated in this group — callers must inherit the value from the
    current base (FM/BASE) when resolving effective conditions.
    """

    __tablename__ = "taf_periods"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    taf_id       = Column(Integer, ForeignKey("tafs.id"), nullable=False)
    period_type  = Column(String(10), nullable=False)  # BASE|FM|BECMG|TEMPO|PROB
    period_seq   = Column(Integer,    nullable=False)  # chronological order in TAF

    valid_from   = Column(String, nullable=False)  # ISO-8601
    valid_to     = Column(String, nullable=False)  # ISO-8601

    # --- Wind (NULL = not specified in this group) ---
    wind_dir      = Column(Integer)  # degrees true; NULL means variable (VRB)
    wind_variable = Column(Integer, default=0)  # 1 if VRB
    wind_speed    = Column(Integer)  # knots
    wind_gust     = Column(Integer)  # knots; NULL if no gust forecast

    # --- Visibility (NULL = not specified) ---
    # Stored in statute miles.  "P6SM" (greater-than) stores 6.0 + vis_greater=1.
    visibility_sm  = Column(Float)
    visibility_gt  = Column(Integer, default=0)  # 1 when prefixed with "P"

    # --- Ceiling (NULL = clear / no ceiling specified) ---
    # Ceiling = lowest BKN, OVC, or VV layer height in feet AGL.
    ceiling_ft       = Column(Integer)
    ceiling_coverage = Column(String(5))  # "BKN", "OVC", "VV", or NULL when clear

    # Full raw sky string for reference (e.g. "FEW040 SCT080 BKN120")
    sky_string  = Column(String(120))

    # --- Weather phenomena (NULL or empty list = no significant weather) ---
    # Stored as a JSON list of raw phenomenon tokens, e.g. ["-RA", "TSRA", "FG"]
    weather_phenomena = Column(JSON)

    # --- PROB group metadata ---
    probability = Column(Integer)  # 30 or 40; NULL for non-PROB periods

    taf = relationship("TAF", back_populates="periods")

    __table_args__ = (
        Index("ix_taf_period_taf_seq", "taf_id", "period_seq"),
    )

    def __repr__(self) -> str:
        return (
            f"<TAFPeriod {self.period_type} seq={self.period_seq} "
            f"{self.valid_from}–{self.valid_to}>"
        )


# ---------------------------------------------------------------------------
# METAR
# ---------------------------------------------------------------------------

class METAR(Base):
    """One surface observation (METAR / SPECI)."""

    __tablename__ = "metars"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    airport_icao     = Column(String(4), ForeignKey("airports.icao"), nullable=False)
    observation_time = Column(String, nullable=False)  # ISO-8601
    raw_text         = Column(Text,   nullable=False)

    # Decoded fields — NULL when missing or when CAVOK applies
    wind_dir      = Column(Integer)  # degrees; NULL = variable
    wind_variable = Column(Integer, default=0)
    wind_speed    = Column(Integer)  # knots
    wind_gust     = Column(Integer)  # knots; NULL if no gust reported
    visibility_sm    = Column(Float)    # statute miles
    ceiling_ft       = Column(Integer)  # feet AGL; NULL = clear
    ceiling_coverage = Column(String(5))  # "BKN", "OVC", "VV", or NULL when clear

    # JSON list of raw weather tokens observed, e.g. ["-RA", "FG"]
    weather_phenomena = Column(JSON)

    # Derived flight category: VFR | MVFR | IFR | LIFR
    flight_category = Column(String(4))

    airport = relationship("Airport",       back_populates="metars")
    scores  = relationship("ForecastScore", back_populates="metar")

    __table_args__ = (
        UniqueConstraint("airport_icao", "observation_time",
                         name="uq_metar_airport_obs"),
        Index("ix_metar_airport_time", "airport_icao", "observation_time"),
    )

    def __repr__(self) -> str:
        return f"<METAR {self.airport_icao} {self.observation_time} {self.flight_category}>"


# ---------------------------------------------------------------------------
# ForecastScore
# ---------------------------------------------------------------------------

class ForecastScore(Base):
    """
    Accuracy scores for one METAR observation aligned to one TAF.

    ``forecast_hour_offset`` is the number of hours from the TAF's valid_from
    to the METAR's observation_time.  This drives the "accuracy vs. lead time"
    chart: at offset +1 h the TAF is very fresh; at +24 h it may be stale.

    Scores
    ------
    ceiling_coverage_score  1.0 if forecast and observed ceiling coverage type match
                            (BKN/OVC/VV), or both have no ceiling; 0.0 otherwise.
    ceiling_altitude_score  1.0 if forecast ceiling altitude is within ±500 ft of
                            observed; 0.0 otherwise; NULL when either side has no ceiling.
    visibility_score        1.0 if the forecast visibility is within ±1 SM of observed.
    wind_speed_score        1.0 if within ±10 kt.
    wind_dir_score          1.0 if within ±30° (circular arithmetic).
    wx_precision            TP / (TP + FP) across weather-phenomena tokens.
    wx_recall               TP / (TP + FN) across weather-phenomena tokens.
    overall_score           Unweighted mean of all non-NULL parameter scores.

    A NULL score means the parameter could not be evaluated (e.g. no visibility
    was present in either the forecast or the observation).
    """

    __tablename__ = "forecast_scores"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    airport_icao = Column(String(4), ForeignKey("airports.icao"), nullable=False)
    metar_id     = Column(Integer,   ForeignKey("metars.id"),     nullable=False)
    taf_id       = Column(Integer,   ForeignKey("tafs.id"),       nullable=False)

    # Offset in fractional hours (e.g. 1.5 = 90 min into the valid period)
    forecast_hour_offset = Column(Float, nullable=False)

    # Per-parameter accuracy scores (0.0–1.0 or NULL)
    ceiling_coverage_score = Column(Float)
    ceiling_altitude_score = Column(Float)
    visibility_score       = Column(Float)
    wind_speed_score = Column(Float)
    wind_dir_score   = Column(Float)
    wx_precision     = Column(Float)
    wx_recall        = Column(Float)

    overall_score = Column(Float)

    # Absolute differences (|forecast − observed|); NULL when either side is missing
    ceiling_coverage_diff = Column(Integer)  # ordinal coverage scale 0-4
    ceiling_altitude_diff = Column(Integer)  # feet
    visibility_diff       = Column(Float)    # statute miles
    wind_speed_diff       = Column(Integer)  # knots
    wind_dir_diff         = Column(Integer)  # degrees 0-180

    # Flight categories derived from forecasted and observed ceiling/visibility
    fc_flight_category = Column(String(4))  # VFR | MVFR | IFR | LIFR
    ob_flight_category = Column(String(4))  # VFR | MVFR | IFR | LIFR

    # 1 when the observation fell inside an active TEMPO or PROB window.
    # Stored for analysis but not used to change scores.
    tempo_active = Column(Integer, default=0)

    airport = relationship("Airport",  back_populates="scores")
    metar   = relationship("METAR",    back_populates="scores")
    taf     = relationship("TAF",      back_populates="scores")

    __table_args__ = (
        UniqueConstraint("metar_id", "taf_id", name="uq_score_metar_taf"),
        Index("ix_score_airport_offset", "airport_icao", "forecast_hour_offset"),
        Index("ix_score_airport_metar", "airport_icao", "metar_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<ForecastScore {self.airport_icao} "
            f"offset={self.forecast_hour_offset:.1f}h "
            f"overall={self.overall_score}>"
        )


# ---------------------------------------------------------------------------
# ApiCache
# ---------------------------------------------------------------------------

class ApiCache(Base):
    """
    Persistent key-value cache for expensive API responses.
    Survives server restarts. Keyed by endpoint + parameters.
    """
    __tablename__ = "api_cache"

    key          = Column(String, primary_key=True)
    data         = Column(JSON,   nullable=False)
    computed_at  = Column(String, nullable=False)  # ISO-8601 UTC
