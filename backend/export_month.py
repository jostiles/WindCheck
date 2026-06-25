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


# Explicit column lists matching the current prod schema (excludes legacy columns)
TABLE_COLUMNS = {
    "airports": [
        "icao", "name", "city", "state", "country", "lat", "lon",
        "elevation_ft", "wfo", "climate_region",
    ],
    "tafs": [
        "id", "airport_icao", "issue_time", "valid_from", "valid_to",
        "raw_text", "is_amendment", "is_correction",
    ],
    "taf_periods": [
        "id", "taf_id", "period_type", "period_seq", "valid_from", "valid_to",
        "wind_dir", "wind_variable", "wind_speed", "wind_gust",
        "visibility_sm", "visibility_gt", "ceiling_ft", "ceiling_coverage",
        "sky_string", "weather_phenomena", "probability",
    ],
    "metars": [
        "id", "airport_icao", "observation_time", "raw_text",
        "wind_dir", "wind_variable", "wind_speed", "wind_gust",
        "visibility_sm", "ceiling_ft", "ceiling_coverage",
        "weather_phenomena", "flight_category",
    ],
    "forecast_scores": [
        "id", "airport_icao", "metar_id", "taf_id", "forecast_hour_offset",
        "ceiling_coverage_score", "ceiling_altitude_score",
        "visibility_score", "wind_speed_score", "wind_dir_score",
        "wx_precision", "wx_recall", "overall_score", "tempo_active",
        "ceiling_coverage_diff", "ceiling_altitude_diff",
        "visibility_diff", "wind_speed_diff", "wind_dir_diff",
        "fc_flight_category", "ob_flight_category",
    ],
}


def export_table(session, table, columns, rows, out):
    if not rows:
        return
    # Use explicit prod-schema columns, falling back to row fields
    prod_cols = TABLE_COLUMNS.get(table)
    if prod_cols:
        # Filter to columns that actually exist in the row
        row_fields = rows[0]._fields
        use_cols = [c for c in prod_cols if c in row_fields]
    else:
        use_cols = list(rows[0]._fields)

    cols_str = ", ".join(use_cols)
    out.write(f"-- {table}: {len(rows)} rows\n")
    for row in rows:
        vals = ", ".join(q(getattr(row, c)) for c in use_cols)
        out.write(f"INSERT OR IGNORE INTO {table} ({cols_str}) VALUES ({vals});\n")
    out.write("\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("month", help="Month to export, e.g. 2026-05")
    parser.add_argument("--out", help="Output file (default: stdout)")
    parser.add_argument("--from-date", help="Start date inclusive, e.g. 2026-05-01")
    parser.add_argument("--to-date",   help="End date exclusive, e.g. 2026-05-21")
    args = parser.parse_args()

    month = args.month
    out = open(args.out, "w") if args.out else sys.stdout

    init_db()

    out.write(f"-- Export for {month} ({args.from_date or ''} to {args.to_date or ''})\n")
    out.write("PRAGMA foreign_keys=OFF;\nBEGIN;\n\n")

    with get_session() as session:
        # 1. METARs for this date range
        if args.from_date and args.to_date:
            metar_where = "observation_time >= :from_date AND observation_time < :to_date"
            metar_params = {"from_date": args.from_date, "to_date": args.to_date}
        else:
            metar_where = "substr(observation_time, 1, 7) = :month"
            metar_params = {"month": month}

        metars = session.execute(text(f"""
            SELECT * FROM metars
            WHERE {metar_where}
            ORDER BY id
        """), metar_params).fetchall()

        metar_ids = [r.id for r in metars]
        if not metar_ids:
            print(f"No METARs found for {month}", file=sys.stderr)
            sys.exit(1)

        airport_icaos = list({r.airport_icao for r in metars})

        # 2. forecast_scores for those METARs
        score_cols = ", ".join(TABLE_COLUMNS["forecast_scores"])
        scores = session.execute(text(f"""
            SELECT {score_cols} FROM forecast_scores
            WHERE metar_id IN (
                SELECT id FROM metars
                WHERE {metar_where}
            )
            ORDER BY id
        """), metar_params).fetchall()

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
