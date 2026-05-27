#!/usr/bin/env python3
"""
scheduler.py — Hourly ingest scheduler for TAF accuracy.

Runs the full ingestion pipeline on a fixed interval.  Designed to run as a
long-lived background process managed by launchd (macOS) or any process
supervisor.

Each cycle:
  1. Fetches the latest TAF + 30 h of METARs for every station.
  2. Scores all unscored (METAR, TAF) pairs in the database.
  3. Sleeps until the next scheduled run.

The interval defaults to 60 minutes — aligned to the typical TAF issuance
schedule.  Shorter intervals (e.g. 30 min) increase the chance of catching
fresh METARs shortly after they post.

Usage
-----
  python3 scheduler.py                         # all 190 bundled stations, 60-min cycle
  python3 scheduler.py --interval 30           # run every 30 minutes
  python3 scheduler.py --airports KORD KJFK    # specific stations only
  python3 scheduler.py --workers 8 --hours 30  # tune concurrency + METAR window
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

# Ensure the backend package is importable regardless of working directory
sys.path.insert(0, str(Path(__file__).parent))

from database import init_db
from ingest import process_station, US_TAF_STATIONS

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "scheduler.log"


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    fmt   = "%(asctime)s %(levelname)-8s %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    handlers: list[logging.Handler] = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE),
    ]
    logging.basicConfig(level=level, format=fmt, datefmt=datefmt, handlers=handlers)


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Graceful shutdown
# ---------------------------------------------------------------------------

_shutdown = False


def _handle_signal(sig, _frame):
    global _shutdown
    logger.info("Received signal %s — finishing current cycle then exiting.", sig)
    _shutdown = True


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT,  _handle_signal)

# ---------------------------------------------------------------------------
# One ingest cycle
# ---------------------------------------------------------------------------

def run_cycle(stations: list[str], workers: int, hours: int) -> dict:
    """
    Fetch + score all ``stations`` concurrently.

    Returns aggregate stats:  total, ok, failed, new_tafs, new_metars, new_scores
    """
    totals = dict(total=len(stations), ok=0, failed=0,
                  new_tafs=0, new_metars=0, new_scores=0)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(process_station, icao, hours): icao for icao in stations}
        for future in as_completed(futures):
            icao = futures[future]
            try:
                s = future.result()
                totals["ok"]         += 1
                totals["new_tafs"]   += s.get("tafs_new", 0)
                totals["new_metars"] += s.get("metars_new", 0)
                totals["new_scores"] += s.get("scores_new", 0)
                if s.get("errors"):
                    logger.debug("%s warnings: %s", icao, s["errors"])
            except Exception as exc:
                totals["failed"] += 1
                logger.warning("Station %s failed: %s", icao, exc)

    return totals

# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="TAF accuracy ingest scheduler")
    grp = parser.add_mutually_exclusive_group()
    grp.add_argument("--airports", nargs="+", metavar="ICAO",
                     help="Specific airport codes (default: all bundled stations)")
    grp.add_argument("--all", action="store_true", default=True,
                     help="Process all bundled US TAF stations (default)")
    parser.add_argument("--interval", type=int, default=60, metavar="MINUTES",
                        help="Minutes between cycles (default: 60)")
    parser.add_argument("--workers",  type=int, default=6, metavar="N",
                        help="Concurrent fetch workers per cycle (default: 6)")
    parser.add_argument("--hours",    type=int, default=30, metavar="N",
                        help="METAR lookback window in hours (default: 30)")
    parser.add_argument("--once",     action="store_true",
                        help="Run one cycle then exit (useful for testing)")
    parser.add_argument("--verbose",  "-v", action="store_true")
    args = parser.parse_args()

    _setup_logging(args.verbose)

    stations = ([a.upper() for a in args.airports] if args.airports else US_TAF_STATIONS)
    interval_s = args.interval * 60

    logger.info("=" * 60)
    logger.info("TAF accuracy scheduler starting")
    logger.info("  Stations : %d", len(stations))
    logger.info("  Interval : %d min", args.interval)
    logger.info("  Workers  : %d", args.workers)
    logger.info("  METAR window: %d h", args.hours)
    logger.info("  Log file : %s", LOG_FILE)
    logger.info("=" * 60)

    init_db()

    cycle = 0
    while not _shutdown:
        cycle += 1
        started = time.monotonic()
        logger.info("── Cycle %d started at %s UTC ──",
                    cycle, datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"))

        try:
            stats = run_cycle(stations, args.workers, args.hours)
            elapsed = time.monotonic() - started
            logger.info(
                "Cycle %d done in %.1f s — %d/%d stations OK | "
                "+%d TAFs  +%d METARs  +%d scores",
                cycle, elapsed,
                stats["ok"], stats["total"],
                stats["new_tafs"], stats["new_metars"], stats["new_scores"],
            )
        except Exception as exc:
            logger.error("Cycle %d crashed: %s", cycle, exc, exc_info=True)

        if args.once or _shutdown:
            break

        # Sleep in short increments so SIGTERM is handled promptly
        next_run = time.monotonic() + interval_s
        logger.info("Next cycle in %d min — sleeping …", args.interval)
        while time.monotonic() < next_run and not _shutdown:
            time.sleep(5)

    logger.info("Scheduler stopped after %d cycle(s).", cycle)


if __name__ == "__main__":
    main()
