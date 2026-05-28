"""
backfill_scores.py — Re-score all existing ForecastScore rows using the
current scoring functions.

Run from the backend directory:
  python backfill_scores.py

The script reads every ForecastScore row, re-runs score_metar_vs_taf() on the
associated METAR and TAF, and overwrites the score columns in place.  It
commits in batches to avoid holding a massive transaction open.
"""

import logging
import os
import sys
import time

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, joinedload

from models import ForecastScore, METAR, TAF
from ingest import _taf_orm_to_dict, _metar_orm_to_dict
from scoring import score_metar_vs_taf

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

DB_PATH   = os.getenv("TAF_DB_PATH", "../data/taf_accuracy.db")
BATCH     = 500   # rows per commit

def main() -> None:
    engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)

    with Session(engine) as session:
        total = session.query(ForecastScore).count()
        logger.info("Total ForecastScore rows to rescore: %d", total)

        updated = 0
        errors  = 0
        start   = time.time()

        # Stream rows in offset batches so we don't load the whole table at once
        offset = 0
        while True:
            batch = (
                session.query(ForecastScore)
                .options(
                    joinedload(ForecastScore.metar),
                    joinedload(ForecastScore.taf).joinedload(TAF.periods),
                )
                .order_by(ForecastScore.id)
                .offset(offset)
                .limit(BATCH)
                .all()
            )
            if not batch:
                break

            for row in batch:
                try:
                    metar_dict  = _metar_orm_to_dict(row.metar)
                    taf_dict    = _taf_orm_to_dict(row.taf)
                    new_score   = score_metar_vs_taf(
                        metar_dict, taf_dict, taf_dict["periods"]
                    )
                    if new_score is None:
                        errors += 1
                        continue

                    row.ceiling_coverage_score = new_score["ceiling_coverage_score"]
                    row.ceiling_altitude_score = new_score["ceiling_altitude_score"]
                    row.visibility_score       = new_score["visibility_score"]
                    row.wind_speed_score       = new_score["wind_speed_score"]
                    row.wind_dir_score         = new_score["wind_dir_score"]
                    row.wx_precision           = new_score["wx_precision"]
                    row.wx_recall              = new_score["wx_recall"]
                    row.overall_score          = new_score["overall_score"]
                    updated += 1

                except Exception as exc:
                    logger.warning("Row %d failed: %s", row.id, exc)
                    errors += 1

            session.commit()
            offset += BATCH

            pct = min(100, round((offset / total) * 100))
            elapsed = time.time() - start
            logger.info(
                "Progress: %d/%d rows (%.0f%%) — %.1f s elapsed",
                min(offset, total), total, pct, elapsed,
            )

    elapsed = time.time() - start
    logger.info(
        "Done. Updated: %d  Errors: %d  Time: %.1f s",
        updated, errors, elapsed,
    )


if __name__ == "__main__":
    main()
