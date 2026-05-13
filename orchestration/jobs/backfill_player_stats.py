"""
orchestration/jobs/backfill_player_stats.py
---------------------------------------------
One-shot backfill of AFL player stats from AFL Tables (afltables.com).

Populates the player_stats and player_lineups tables for all historical
seasons so that PlayerAvailabilityExtractor produces non-null features.

AFL Tables CSV is free, no API key required.
Sleep of 1s between season requests (polite crawl delay requested by site).

Usage:
    python -m orchestration.jobs.backfill_player_stats
    python -m orchestration.jobs.backfill_player_stats --seasons 2020 2021 2022
    python -m orchestration.jobs.backfill_player_stats --dry-run
"""

from __future__ import annotations

import argparse
import sys
import time

from loguru import logger

from collectors.player_collector import PlayerCollector
from db.session import db_session


def run(seasons: list[int] | None = None, dry_run: bool = False) -> None:
    """Backfill player stats for the given seasons (default: 2015–2025)."""
    if seasons is None:
        seasons = list(range(2015, 2026))

    logger.info(
        f"backfill_player_stats: {'DRY RUN — ' if dry_run else ''}"
        f"backfilling {len(seasons)} seasons: {seasons[0]}–{seasons[-1]}"
    )

    if dry_run:
        logger.info("backfill_player_stats: dry run — no DB writes.")
        return

    total_rows = 0
    for season in seasons:
        with db_session() as db:
            collector = PlayerCollector(db)
            logger.info(f"backfill_player_stats: fetching season {season}...")
            try:
                n = collector.fetch_and_store_season(season)
                total_rows += n
                logger.info(f"backfill_player_stats: season {season} -> {n} rows inserted.")
            except Exception as exc:
                logger.error(f"backfill_player_stats: season {season} FAILED: {exc}")

    logger.info(
        f"backfill_player_stats: complete. {total_rows} total player stat rows inserted."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill AFL player stats from AFL Tables.")
    parser.add_argument(
        "--seasons", type=int, nargs="+",
        help="Seasons to backfill (default: 2015–2025)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print plan without writing.")
    args = parser.parse_args()

    try:
        run(seasons=args.seasons, dry_run=args.dry_run)
    except Exception:
        logger.exception("backfill_player_stats: FATAL")
        sys.exit(1)
