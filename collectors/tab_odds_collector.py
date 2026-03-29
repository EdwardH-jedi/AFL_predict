"""
collectors/tab_odds_collector.py
---------------------------------
Facade for AFL H2H odds collection.

Delegates HTTP + snapshot-saving to OddsApiCollector and
parsing/validation to collectors/parsers/odds_parser.py.

Data source: The Odds API (the-odds-api.com), AU region.
  - Covers TAB, Sportsbet, Unibet, Betfair AU and others.
  - TAB odds appear when available from the API feed.
  - TODO: Confirm TAB bookmaker key ('tab') is present in your subscription.

IMPORTANT: This is the only odds data entry point for the ingest layer.
"""

from __future__ import annotations

from loguru import logger

from collectors.odds_api_collector import OddsApiCollector
from collectors.parsers.odds_parser import ParsedOddsEvent, parse_events
from config.settings import get_settings

settings = get_settings()


class TABOddsCollector:
    """
    Fetch and parse AFL H2H odds snapshots.

    Usage:
        collector = TABOddsCollector()
        events = collector.fetch_upcoming_h2h()
    """

    def __init__(self) -> None:
        self._http = OddsApiCollector()
        self._bookmaker_preference = [
            k.strip()
            for k in settings.odds_bookmaker_preference.split(",")
            if k.strip()
        ]

    def fetch_upcoming_h2h(self) -> list[ParsedOddsEvent]:
        """
        Fetch H2H odds for all upcoming AFL matches.

        Saves raw JSON snapshot to storage/raw_snapshots/odds_api/ before parsing.
        Events with no usable bookmaker odds are skipped with a debug log.

        Returns:
            List of ParsedOddsEvent (empty if ODDS_API_KEY not configured).
        """
        raw = self._http.fetch_h2h_odds()

        if not raw:
            return []

        events = parse_events(raw, self._bookmaker_preference)

        for e in events:
            if e.parse_warnings:
                logger.debug(
                    f"tab_odds_collector: event {e.external_event_id} "
                    f"warnings: {e.parse_warnings}"
                )

        logger.info(
            f"tab_odds_collector: parsed {len(events)} events "
            f"(preference: {self._bookmaker_preference})"
        )
        return events

    @staticmethod
    def compute_implied_probs(
        home_odds: float, away_odds: float
    ) -> tuple[float, float, float]:
        """
        Convert decimal odds to overround-normalised implied probabilities.

        Returns (home_prob, away_prob, overround).
        Overround > 1.0 represents bookmaker margin.
        """
        if home_odds <= 1.0 or away_odds <= 1.0:
            raise ValueError(
                f"Odds must be > 1.0 for probability conversion "
                f"(got home={home_odds}, away={away_odds})."
            )
        raw_home = 1.0 / home_odds
        raw_away = 1.0 / away_odds
        overround = raw_home + raw_away
        home_prob = raw_home / overround
        away_prob = raw_away / overround
        return round(home_prob, 6), round(away_prob, 6), round(overround, 6)
