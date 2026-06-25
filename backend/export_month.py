"""
export_month.py — export one month of data as INSERT OR IGNORE SQL statements.

Exports in FK-safe order: airports → tafs → taf_periods → metars → forecast_scores
Only exports rows whose METAR observation_time falls within the given month.

Usage:
    python backend/export_month.py 2026-05 > /tmp/2026-05.sql
    python backend/export_month.py 2026-05 --out data/2026-05.sql
"""

import sys, os, argparse
sys.path.insert(0, os.path.dirname(__file__))

from database import get_session, init_db
from sqlalchemy import text

def q(v):
    """Quote a value for SQL."""
    if v is None:
        return "NULL"
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def export_table(session, table, columns, rows, out):
    if not rows:
        return
    cols = ", ".join(columns)
    out.write(f"-- {table}: {len(rows)} rows\n")
    for row in rows:
        vals = ", ".join(q(getattr(row, c, None) or row[i]) for i, c in enumerate(columns))
        out.write(f"INSERT OR IGNORE INTO {table} ({cols}) VALUES ({vals});\n")
    out.write("\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("month", help="Month to export, e.g. 2026-05")
    parser.add_argument("--out", help="Output file (default: stdout)")
    args = parser.parse_args()

    month = args.month  # e.g. "2026-05"
    out = open(args.out, "w") if args.out else sys.stdout

    init_db()

    out.write(f"-- Export for {month}\n")
    out.write("PRAGMA foreign_keys=OFF;\nBEGIN;\n\n")

    with get_session() as session:
        # 1. METARs for this month
        metars = session.execute(text("""
            SELECT * FROM metars
            WHERE substr(observation_time, 1, 7) = :month
            ORDER BY id
        """), {"month": month}).fetchall()

        metar_ids = [r.id for r in metars]
        if not metar_ids:
            print(f"No METARs found for {month}", file=sys.stderr)
            sys.exit(1)

        airport_icaos = list({r.airport_icao for r in metars})

        # 2. forecast_scores for those METARs
        scores = session.execute(text("""
            SELECT * FROM forecast_scores
            WHERE metar_id IN (
                SELECT id FROM metars
                WHERE substr(observation_time, 1, 7) = :month
            )
            ORDER BY id
        """), {"month": month}).fetchall()

        taf_ids = list({r.taf_id for r in scores})

        # 3. TAFs referenced by those scores
        tafs = []
        taf_period_rows = []
        if taf_ids:
            CHUNK = 500
            for i in range(0, len(taf_ids), CHUNK):
                chunk = taf_ids[i:i+CHUNK]
                placeholders = ",".join(str(x) for x in chunk)
                tafs += session.execute(text(
                    f"SELECT * FROM tafs WHERE id IN ({placeholders})"
                )).fetchall()
                taf_period_rows += session.execute(text(
                    f"SELECT * FROM taf_periods WHERE taf_id IN ({placeholders}) ORDER BY taf_id, period_seq"
                )).fetchall()

        # 4. Airports
        airports = []
        if airport_icaos:
            placeholders = ",".join(f"'{i}'" for i in airport_icaos)
            airports = session.execute(text(
                f"SELECT * FROM airports WHERE icao IN ({placeholders})"
            )).fetchall()

    # Write in FK order
    if airports:
        cols = list(airports[0]._fields)
        export_table(session, "airports", cols, airports, out)

    if tafs:
        cols = list(tafs[0]._fields)
        export_table(session, "tafs", cols, tafs, out)

    if taf_period_rows:
        cols = list(taf_period_rows[0]._fields)
        export_table(session, "taf_periods", cols, taf_period_rows, out)

    if metars:
        cols = list(metars[0]._fields)
        export_table(session, "metars", cols, metars, out)

    if scores:
        cols = list(scores[0]._fields)
        export_table(session, "forecast_scores", cols, scores, out)

    out.write("COMMIT;\nPRAGMA foreign_keys=ON;\n")

    if args.out:
        out.close()
        print(f"Exported {month} to {args.out}", file=sys.stderr)
        print(f"  airports:       {len(airports):,}", file=sys.stderr)
        print(f"  tafs:           {len(tafs):,}", file=sys.stderr)
        print(f"  taf_periods:    {len(taf_period_rows):,}", file=sys.stderr)
        print(f"  metars:         {len(metars):,}", file=sys.stderr)
        print(f"  forecast_scores:{len(scores):,}", file=sys.stderr)


if __name__ == "__main__":
    main()
