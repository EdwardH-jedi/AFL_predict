"""
collectors/afl_collector.py
----------------------------
Facade for AFL fixture and result data collection.

Delegates HTTP + snapshot-saving to SquiggleCollector and
parsing/validation to collectors/parsers/squiggle_parser.py.

This is the only AFL data entry point for the ingest layer — all other
modules should use this class rather than SquiggleCollector directly.

Data source: Squiggle API (squiggle.com.au) — public, free, no API key.
"""

from __future__ import annotations

from loguru import logger

from collectors.parsers.squiggle_parser import ParsedGame, ParsedTeam, parse_games, parse_teams
from collectors.squiggle_collector import SquiggleCollector


class AFLCollector:
    """
    Fetch and parse AFL fixtures, results, and team reference data.

    Usage:
        collector = AFLCollector()
        games = collector.fetch_games(season=2025)
        teams = collector.fetch_teams()
    """

    def __init__(self) -> None:
        self._http = SquiggleCollector()

    def fetch_games(
        self, season: int, round_number: int | None = None
    ) -> list[ParsedGame]:
        """
        Fetch all games for a season (or a specific round).

        Saves raw JSON snapshot to storage/raw_snapshots/squiggle/ before parsing.
        Invalid individual games are logged and skipped — the rest are returned.

        Args:
            season:       AFL season year (e.g. 2025).
            round_number: Optional round filter. None = all rounds.

        Returns:
            List of ParsedGame (may be empty if Squiggle returns no games).
        """
        raw = self._http.fetch_games(season=season, round_number=round_number)
        games = parse_games(raw)

        for g in games:
            if g.parse_warnings:
                logger.debug(
                    f"afl_collector: game {g.external_id} parsed with "
                    f"warnings: {g.parse_warnings}"
                )

        logger.info(
            f"afl_collector: fetched {len(games)} games "
            f"(season={season}, round={round_number})"
        )
        return games

    def fetch_teams(self) -> list[ParsedTeam]:
        """
        Fetch AFL team reference data.

        Returns:
            List of ParsedTeam.
        """
        raw = self._http.fetch_teams()
        teams = parse_teams(raw)
        logger.info(f"afl_collector: fetched {len(teams)} teams")
        return teams
