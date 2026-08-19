"""
orchestration/jobs/fetch_weather.py
--------------------------------------
Job: Fetch weather data for upcoming and/or historical AFL matches.

Pipeline position:
  Runs daily after ingest_afl (needs match_time and venue to be populated).
  Typically scheduled at 06:00 AEST, before build_features at 07:30.

CLI usage:
    python -m orchestration.jobs.fetch_weather               # upcoming 14 days
    python -m orchestration.jobs.fetch_weather --season 2024 # historical backfill
    python -m orchestration.jobs.fetch_weather --days 7      # upcoming 7 days only
"""

from __future__ import annotations

import argparse
import sys
import time

from loguru import logger

from collectors.weather_collector import WeatherCollector
from config.settings import get_settings
from db.session import db_session

settings = get_settings()


def run(season: int | None = None, days_ahead: int = 14) -> int:
    """
    Fetch weather for upcoming matches or historical season.

    Args:
        season:     If provided, backfill the entire season.
        days_ahead: Days of upcoming matches to fetch forecast for.

    Returns:
        Number of weather records created/updated.
    """
    start = time.monotonic()
    logger.info(f"==> fetch_weather: starting (season={season}, days_ahead={days_ahead})")

    with db_session() as db:
        collector = WeatherCollector(db)

        if season is not None:
            count = collector.fetch_historical(season)
        else:
            count = collector.fetch_upcoming(days_ahead=days_ahead)

    duration = time.monotonic() - start
    logger.info(f"==> fetch_weather: done — {count} records in {duration:.1f}s")
    return count


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fetch weather data for AFL matches.")
    p.add_argument("--season", type=int, default=None,
                   help="Historical season to backfill (e.g. 2024).")
    p.add_argument("--days", type=int, default=14,
                   help="Days ahead for upcoming forecast (default 14).")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    try:
        run(season=args.season, days_ahead=args.days)
    except Exception:
        logger.exception("fetch_weather: FAILED")
        sys.exit(1)
