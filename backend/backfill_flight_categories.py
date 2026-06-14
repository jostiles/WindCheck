"""
backfill_flight_categories.py — populate fc_flight_category and ob_flight_category
on existing forecast_scores rows using pure SQL for speed.

Observed: directly from metars.ceiling_ft / metars.visibility_sm.
Forecast: from the TAF period (BASE or FM) whose window covers the observation time.
          BECMG transitions are approximated (rare edge case, negligible impact).

Run once:
    python backend/backfill_flight_categories.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from database import get_session, init_db
from sqlalchemy import text

BATCH = 50_000

# SQL CASE expression: OR logic, NULL ceiling/vis = VFR
def _cat_expr(ceil_col, vis_col):
    return f"""
        CASE
            WHEN ({ceil_col} IS NOT NULL AND {ceil_col} < 500)
              OR ({vis_col}  IS NOT NULL AND {vis_col}  < 1.0) THEN 'LIFR'
            WHEN ({ceil_col} IS NOT NULL AND {ceil_col} < 1000)
              OR ({vis_col}  IS NOT NULL AND {vis_col}  < 3.0) THEN 'IFR'
            WHEN ({ceil_col} IS NOT NULL AND {ceil_col} < 3000)
              OR ({vis_col}  IS NOT NULL AND {vis_col}  < 5.0) THEN 'MVFR'
            ELSE 'VFR'
        END
    """

OB_CAT  = _cat_expr("m.ceiling_ft",  "m.visibility_sm")
FC_CAT  = _cat_expr("tp.ceiling_ft", "tp.visibility_sm")

UPDATE_SQL = f"""
    UPDATE forecast_scores
    SET
        ob_flight_category = (
            SELECT {OB_CAT}
            FROM metars m
            WHERE m.id = forecast_scores.metar_id
        ),
        fc_flight_category = (
            SELECT {FC_CAT}
            FROM taf_periods tp
            JOIN metars m ON m.id = forecast_scores.metar_id
            WHERE tp.taf_id = forecast_scores.taf_id
              AND tp.period_type IN ('BASE', 'FM')
              AND tp.valid_from <= m.observation_time
            ORDER BY tp.valid_from DESC
            LIMIT 1
        )
    WHERE id IN (
        SELECT id FROM forecast_scores
        WHERE fc_flight_category IS NULL
        LIMIT {BATCH}
    )
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

    updated = 0
    while True:
        with get_session() as session:
            result = session.execute(text(UPDATE_SQL))
            n = result.rowcount

        if n == 0:
            break
        updated += n
        pct = 100 * updated / total
        print(f"  {updated:,} / {total:,} ({pct:.1f}%)")

    print(f"Done. {updated:,} rows backfilled.")

if __name__ == "__main__":
    main()
