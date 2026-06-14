"""
backfill_flight_categories.py — populate fc_flight_category and ob_flight_category
on existing forecast_scores rows.

Observed category: derived from metars.ceiling_ft + metars.visibility_sm (direct join).
Forecast category: derived by re-running resolve_taf_conditions_at_time for each row.

Run once:
    python backend/backfill_flight_categories.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from database import get_session, init_db, _engine
from sqlalchemy import text
from scoring import flight_category, resolve_taf_conditions_at_time, _iso
from ingest import _taf_orm_to_dict
from models import TAF

BATCH = 2_000


def _ob_category_sql():
    """SQL CASE expression for observed flight category from metars columns."""
    return """
        CASE
            WHEN (m.ceiling_ft IS NOT NULL AND m.ceiling_ft < 500)
              OR (m.visibility_sm IS NOT NULL AND m.visibility_sm < 1.0) THEN 'LIFR'
            WHEN (m.ceiling_ft IS NOT NULL AND m.ceiling_ft < 1000)
              OR (m.visibility_sm IS NOT NULL AND m.visibility_sm < 3.0) THEN 'IFR'
            WHEN (m.ceiling_ft IS NOT NULL AND m.ceiling_ft < 3000)
              OR (m.visibility_sm IS NOT NULL AND m.visibility_sm < 5.0) THEN 'MVFR'
            ELSE 'VFR'
        END
    """


def main():
    init_db()

    with get_session() as session:
        total = session.execute(text(
            "SELECT COUNT(*) FROM forecast_scores WHERE fc_flight_category IS NULL"
        )).scalar()

    print(f"{total:,} rows to backfill")
    if total == 0:
        print("Nothing to do.")
        return

    # Cache TAFs to avoid repeated DB hits
    taf_cache: dict = {}

    updated = 0
    while True:
        with get_session() as session:
            rows = session.execute(text("""
                SELECT
                    fs.id,
                    fs.taf_id,
                    fs.metar_id,
                    m.observation_time,
                    m.ceiling_ft   AS ob_ceil,
                    m.visibility_sm AS ob_vis
                FROM forecast_scores fs
                JOIN metars m ON fs.metar_id = m.id
                WHERE fs.fc_flight_category IS NULL
                LIMIT :batch
            """), {"batch": BATCH}).fetchall()

            if not rows:
                break

            updates = []
            for row in rows:
                ob_cat = flight_category(row.ob_ceil, row.ob_vis)

                # Get TAF periods for forecast category
                taf_id = row.taf_id
                if taf_id not in taf_cache:
                    taf_orm = session.query(TAF).get(taf_id)
                    if taf_orm:
                        taf_cache[taf_id] = _taf_orm_to_dict(taf_orm)
                    else:
                        taf_cache[taf_id] = None

                taf = taf_cache.get(taf_id)
                fc_cat = "VFR"  # fallback
                if taf:
                    obs_time = _iso(row.observation_time)
                    taf_from = _iso(taf["valid_from"])
                    taf_to   = _iso(taf["valid_to"])
                    base_cond, _ = resolve_taf_conditions_at_time(
                        taf.get("periods", []), obs_time, taf_from, taf_to
                    )
                    if base_cond:
                        fc_cat = flight_category(
                            base_cond.get("ceiling_ft"),
                            base_cond.get("visibility_sm"),
                        )

                updates.append({
                    "id":     row.id,
                    "fc_cat": fc_cat,
                    "ob_cat": ob_cat,
                })

            for u in updates:
                session.execute(text("""
                    UPDATE forecast_scores
                    SET fc_flight_category = :fc_cat,
                        ob_flight_category = :ob_cat
                    WHERE id = :id
                """), u)

            updated += len(updates)

        # Clear cache periodically to avoid unbounded memory growth
        if len(taf_cache) > 5000:
            taf_cache.clear()

        print(f"  {updated:,} / {total:,} ({100*updated/total:.1f}%)")

    print(f"Done. {updated:,} rows backfilled.")


if __name__ == "__main__":
    main()
