"""
features/extractors/venue_performance.py
------------------------------------------
Venue-specific win-rate extractor.

Some teams perform markedly better or worse at specific grounds independent
of their general ELO rating — e.g. Geelong at Kardinia Park, Hawthorn at
the MCG, interstate teams visiting Perth. This extractor captures that
venue-specific signal.

Features produced:
  - home_venue_win_rate:  home team's historical win rate at this exact venue
                          (None if fewer than MIN_GAMES prior games at venue)
  - away_venue_win_rate:  away team's historical win rate at this exact venue
                          (from the away team's perspective — i.e. their wins
                           regardless of which side they were on)
  - venue_home_advantage: home_venue_win_rate - away_venue_win_rate
                          positive = home team historically dominates this ground

Leakage policy:
  Only completed matches processed strictly before the current match in the
  sorted chronological pass contribute to venue statistics.

Design note:
  win rate is computed over all prior games at the venue regardless of
  home/away designation, from each team's perspective (did the team win
  the game, not "was the team listed as home").  This captures pure
  venue-familiarity advantage.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from loguru import logger

from db.models.matches import Match
from features.extractors.base import BaseExtractor

_MIN_GAMES = 5   # require at least 5 prior games at venue before emitting a rate


@dataclass
class _VenueRecord:
    wins: int = 0
    games: int = 0

    def win_rate(self) -> float:
        return round(self.wins / self.games, 4) if self.games else 0.0


class VenuePerformanceExtractor(BaseExtractor):
    """
    Venue-specific win-rate feature extractor.

    Tracks each (team_id, venue) pair's win/game counts and emits win rates
    for both the home and away teams at the current match venue.
    """

    def extract(self, matches: list[Match]) -> dict[int, dict]:
        # (team_id, venue) → VenueRecord
        records: dict[tuple[int, str], _VenueRecord] = defaultdict(_VenueRecord)

        result: dict[int, dict] = {}

        for match in matches:
            venue = match.venue
            home_id = match.home_team_id
            away_id = match.away_team_id

            if not venue:
                result[match.id] = {
                    "home_venue_win_rate": None,
                    "away_venue_win_rate": None,
                    "venue_home_advantage": None,
                }
                continue

            home_rec = records[(home_id, venue)]
            away_rec = records[(away_id, venue)]

            home_vwr = home_rec.win_rate() if home_rec.games >= _MIN_GAMES else None
            away_vwr = away_rec.win_rate() if away_rec.games >= _MIN_GAMES else None

            adv: float | None = None
            if home_vwr is not None and away_vwr is not None:
                adv = round(home_vwr - away_vwr, 4)

            result[match.id] = {
                "home_venue_win_rate": home_vwr,
                "away_venue_win_rate": away_vwr,
                "venue_home_advantage": adv,
            }

            # Update only for completed matches
            if not match.result:
                continue

            home_won = match.result == "home"
            away_won = match.result == "away"

            records[(home_id, venue)].games += 1
            if home_won:
                records[(home_id, venue)].wins += 1

            records[(away_id, venue)].games += 1
            if away_won:
                records[(away_id, venue)].wins += 1

        logger.debug(
            f"VenuePerformanceExtractor: computed venue features for {len(result)} matches."
        )
        return result
