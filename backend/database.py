"""
database.py — SQLAlchemy engine + session factory and DB initialisation.

Usage
-----
    from database import get_session, init_db

    init_db()  # creates tables on first run
    with get_session() as session:
        session.add(some_orm_object)
        session.commit()
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session

from models import Base

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Database file path — override with TAF_DB_PATH env var.
_DEFAULT_DB = Path(__file__).parent.parent / "data" / "taf_accuracy.db"
DB_PATH     = Path(os.getenv("TAF_DB_PATH", str(_DEFAULT_DB)))

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

def _make_engine(db_path: Path = DB_PATH):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        echo=False,
    )

    # Enable WAL mode for better concurrent read performance
    @event.listens_for(engine, "connect")
    def _set_wal(dbapi_conn, _rec):
        dbapi_conn.execute("PRAGMA journal_mode=WAL")
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    return engine


_engine        = _make_engine()
_SessionLocal  = sessionmaker(bind=_engine, autoflush=False, autocommit=False)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def init_db() -> None:
    """Create all tables defined in models.py (no-op if already exist)."""
    Base.metadata.create_all(bind=_engine)
    _migrate_schema()


def _migrate_schema() -> None:
    """
    Add new columns to existing tables without dropping data.

    SQLite supports ALTER TABLE ADD COLUMN for backward-compatible migrations.
    Each ALTER is wrapped in a try/except so re-running is safe.
    """
    migrations = [
        ("taf_periods",     "ceiling_coverage",        "TEXT"),
        ("metars",          "ceiling_coverage",         "TEXT"),
        ("forecast_scores", "ceiling_coverage_score",   "REAL"),
        ("forecast_scores", "ceiling_altitude_score",   "REAL"),
        ("airports",        "state",                    "TEXT"),
        ("airports",        "wfo",                      "TEXT"),
        ("airports",        "climate_region",            "TEXT"),
        ("tafs",            "is_amendment",              "INTEGER DEFAULT 0"),
        ("tafs",            "is_correction",             "INTEGER DEFAULT 0"),
    ]
    with _engine.connect() as conn:
        for table, column, col_type in migrations:
            try:
                conn.execute(
                    __import__("sqlalchemy").text(
                        f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"
                    )
                )
                conn.commit()
            except Exception:
                pass  # column already exists


@contextmanager
def get_session() -> Session:
    """Context manager that yields a session and handles commit/rollback."""
    session: Session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
