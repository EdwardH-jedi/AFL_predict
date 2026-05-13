"""
orchestration/jobs/backfill_weather.py
----------------------------------------
One-shot historical weather backfill using the Open-Meteo Archive API.

Open-Meteo is completely free, requires no API key, and provides hourly
historical weather back to 1940 at any GPS coordinates.

Fetches weather at kickoff time for every settled AFL match in the given
seasons and stores it in the weather_snapshots table.

~2,200 matches × 0.5s delay = ~18 minutes for a full 2015-2025 backfill.
Already-populated matches are skipped (idempotent).

Usage:
    python -m orchestration.jobs.backfill_weather
    python -m orchestration.jobs.backfill_weather --seasons 2023 2024 2025
    python -m orchestration.jobs.backfill_weather --dry-run
"""

from __future__ import annotations

import argparse
import sys
import time

from loguru import logger

from collectors.weather_collector import WeatherCollector
from db.session import db_session


def run(seasons: list[int] | None = None, dry_run: bool = False) -> None:
    """Backfill weather for the given seasons (default: 2015–2025)."""
    if seasons is None:
        seasons = list(range(2015, 2026))

    logger.info(
        f"backfill_weather: {'DRY RUN — ' if dry_run else ''}"
        f"backfilling {len(seasons)} seasons: {seasons[0]}–{seasons[-1]}"
    )

    if dry_run:
        logger.info("backfill_weather: dry run — no API calls or DB writes.")
        return

    total = 0
    for season in seasons:
        # Use a fresh session per season so a UNIQUE constraint failure in one
        # season does not corrupt the session for subsequent seasons.
        with db_session() as db:
            collector = WeatherCollector(db)
            logger.info(f"backfill_weather: fetching season {season}...")
            try:
                n = collector.fetch_historical(season)
                total += n
                logger.info(f"backfill_weather: season {season} -> {n} weather snapshots stored.")
            except Exception as exc:
                logger.error(f"backfill_weather: season {season} FAILED: {exc}")

    logger.info(f"backfill_weather: complete. {total} weather snapshots stored total.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill AFL historical weather from Open-Meteo.")
    parser.add_argument(
        "--seasons", type=int, nargs="+",
        help="Seasons to backfill (default: 2015–2025)",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    try:
        run(seasons=args.seasons, dry_run=args.dry_run)
    except Exception:
        logger.exception("backfill_weather: FATAL")
        sys.exit(1)
