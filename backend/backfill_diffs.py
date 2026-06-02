"""
backfill_diffs.py — Compute absolute-difference columns for existing forecast_scores rows.

Run once after the columns are added via database migration:

    cd backend && python backfill_diffs.py

Processes rows in ID-range batches; safe to interrupt and re-run.
"""

from __future__ import annotations

import sys
from sqlalchemy import func

from database import get_session, init_db
from models import ForecastScore, METAR, TAF, TAFPeriod
from scoring import score_metar_vs_taf

BATCH_SIZE = 500


def _metar_to_dict(m: METAR) -> dict:
    return {
        "airport_icao":      m.airport_icao,
        "observation_time":  m.observation_time,
        "wind_dir":          m.wind_dir,
        "wind_variable":     m.wind_variable,
        "wind_speed":        m.wind_speed,
        "wind_gust":         m.wind_gust,
        "visibility_sm":     m.visibility_sm,
        "ceiling_ft":        m.ceiling_ft,
        "ceiling_coverage":  m.ceiling_coverage,
        "weather_phenomena": m.weather_phenomena or [],
    }


def _period_to_dict(p: TAFPeriod) -> dict:
    return {
        "period_type":        p.period_type,
        "valid_from":         p.valid_from,
        "valid_to":           p.valid_to,
        "wind_dir":           p.wind_dir,
        "wind_variable":      p.wind_variable,
        "wind_speed":         p.wind_speed,
        "wind_gust":          p.wind_gust,
        "visibility_sm":      p.visibility_sm,
        "visibility_gt":      p.visibility_gt,
        "ceiling_ft":         p.ceiling_ft,
        "ceiling_coverage":   p.ceiling_coverage,
        "weather_phenomena":  p.weather_phenomena or [],
        "probability":        p.probability,
    }


def _taf_to_dict(t: TAF, periods: list[TAFPeriod]) -> dict:
    return {
        "icao":       t.airport_icao,
        "issue_time": t.issue_time,
        "valid_from": t.valid_from,
        "valid_to":   t.valid_to,
        "raw_text":   t.raw_text,
        "periods":    [_period_to_dict(p) for p in periods],
    }


def main() -> None:
    init_db()

    with get_session() as session:
        max_id   = session.query(func.max(ForecastScore.id)).scalar() or 0
        todo_cnt = session.query(func.count(ForecastScore.id)).filter(
            ForecastScore.ceiling_coverage_diff.is_(None)
        ).scalar()

    print(f"Rows needing backfill: {todo_cnt:,}  (max id={max_id:,})")
    if todo_cnt == 0:
        print("Nothing to do.")
        return

    processed = updated = 0
    id_lo = 1

    while id_lo <= max_id:
        id_hi = id_lo + BATCH_SIZE - 1

        with get_session() as session:
            rows = (
                session.query(ForecastScore)
                .filter(
                    ForecastScore.id.between(id_lo, id_hi),
                    ForecastScore.ceiling_coverage_diff.is_(None),
                )
                .all()
            )

            for fs in rows:
                metar_orm = session.get(METAR, fs.metar_id)
                taf_orm   = session.get(TAF,   fs.taf_id)
                if metar_orm is None or taf_orm is None:
                    # Orphaned row — mark as processed with sentinel 0
                    fs.ceiling_coverage_diff = 0
                    continue

                periods_orm = (
                    session.query(TAFPeriod)
                    .filter(TAFPeriod.taf_id == taf_orm.id)
                    .order_by(TAFPeriod.period_seq)
                    .all()
                )

                metar_dict = _metar_to_dict(metar_orm)
                taf_dict   = _taf_to_dict(taf_orm, periods_orm)

                result = score_metar_vs_taf(metar_dict, taf_dict, taf_dict["periods"])
                if result:
                    fs.ceiling_coverage_diff = result.get("ceiling_coverage_diff", 0)
                    fs.ceiling_altitude_diff = result.get("ceiling_altitude_diff")
                    fs.visibility_diff       = result.get("visibility_diff")
                    fs.wind_speed_diff       = result.get("wind_speed_diff")
                    fs.wind_dir_diff         = result.get("wind_dir_diff")
                else:
                    fs.ceiling_coverage_diff = 0  # can't compute; mark done

                updated += 1

            processed += len(rows)

        id_lo = id_hi + 1
        if processed % 5000 == 0 or id_lo > max_id:
            pct = round(id_lo / max_id * 100, 1)
            print(f"  {updated:,} updated  ({pct}%)", end="\r", flush=True)

    print(f"\nDone — {updated:,} rows updated.")


if __name__ == "__main__":
    main()
