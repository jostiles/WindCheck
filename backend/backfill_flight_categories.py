"""
backfill_flight_categories.py — populate fc_flight_category and ob_flight_category
on existing forecast_scores rows using the ceiling/visibility data already in the DB.

Run once after the migration:
    python backend/backfill_flight_categories.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from database import get_session, init_db
from sqlalchemy import text

BATCH = 10_000

CATEGORY_SQL = """
    CASE
        WHEN COALESCE({ceil}, 99999) < 500  OR COALESCE({vis}, 99) < 1.0 THEN 'LIFR'
        WHEN COALESCE({ceil}, 99999) < 1000 OR COALESCE({vis}, 99) < 3.0 THEN 'IFR'
        WHEN COALESCE({ceil}, 99999) < 3000 OR COALESCE({vis}, 99) < 5.0 THEN 'MVFR'
        ELSE 'VFR'
    END
"""

FC_EXPR = CATEGORY_SQL.format(ceil="tp.ceiling_ft", vis="tp.visibility_sm")
OB_EXPR = CATEGORY_SQL.format(ceil="m.ceiling_ft",  vis="m.visibility_sm")

def main():
    init_db()

    # Count rows needing backfill
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
            result = session.execute(text(f"""
                UPDATE forecast_scores
                SET
                    fc_flight_category = (
                        SELECT {FC_EXPR}
                        FROM tafs t
                        JOIN taf_periods tp ON tp.taf_id = t.id
                        JOIN metars m ON m.id = forecast_scores.metar_id
                        WHERE t.id = forecast_scores.taf_id
                          AND m.observation_time >= tp.valid_from
                          AND m.observation_time <  tp.valid_to
                        ORDER BY tp.period_seq DESC
                        LIMIT 1
                    ),
                    ob_flight_category = (
                        SELECT {OB_EXPR}
                        FROM tafs t
                        JOIN taf_periods tp ON tp.taf_id = t.id
                        JOIN metars m ON m.id = forecast_scores.metar_id
                        WHERE t.id = forecast_scores.taf_id
                          AND m.observation_time >= tp.valid_from
                          AND m.observation_time <  tp.valid_to
                        ORDER BY tp.period_seq DESC
                        LIMIT 1
                    )
                WHERE id IN (
                    SELECT id FROM forecast_scores
                    WHERE fc_flight_category IS NULL
                    LIMIT {BATCH}
                )
            """))
            n = result.rowcount

        if n == 0:
            break
        updated += n
        print(f"  updated {updated:,} / {total:,}")

    print(f"Done. {updated:,} rows backfilled.")

if __name__ == "__main__":
    main()
