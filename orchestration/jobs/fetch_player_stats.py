"""
orchestration/jobs/fetch_player_stats.py
------------------------------------------
Job: Fetch AFL player stats from AFL Tables and compute availability index.

Run manually to backfill historical seasons.
Not in the daily pipeline (AFL Tables data is historical-only;
real-time lineup tracking requires a separate announcement scraper).

CLI usage:
    python -m orchestration.jobs.fetch_player_stats --season 2024
    python -m orchestration.jobs.fetch_player_stats --season 2023
"""

from __future__ import annotations

import argparse
import sys
import time

from loguru import logger

from db.session import db_session
from collectors.player_collector import PlayerCollector


def run(season: int) -> int:
    """
    Fetch player stats and compute availability index for a season.

    Args:
        season: AFL season year (e.g. 2024).

    Returns:
        Number of player stat rows inserted.
    """
    start = time.monotonic()
    logger.info(f"==> fetch_player_stats: starting (season={season})")

    with db_session() as db:
        collector = PlayerCollector(db)
        count = collector.fetch_and_store_season(season)

    duration = time.monotonic() - start
    logger.info(f"==> fetch_player_stats: done — {count} rows in {duration:.1f}s")
    return count


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fetch AFL player stats from AFL Tables.")
    p.add_argument("--season", type=int, required=True,
                   help="AFL season year to fetch (e.g. 2024).")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    try:
        run(season=args.season)
    except Exception:
        logger.exception("fetch_player_stats: FAILED")
        sys.exit(1)
