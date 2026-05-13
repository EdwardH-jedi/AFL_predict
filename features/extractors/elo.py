"""
features/extractors/elo.py
----------------------------
ELO rating extractor.

Computes pre-match ELO ratings for both teams by replaying all historical
matches in chronological order. The ELO values recorded for a given match
reflect ratings immediately *before* that match (no leakage).

Design choices:
  - Starting ELO: 1500 for all teams (new entrants also start at 1500).
  - K-factor: 32 (standard; higher than chess due to AFL schedule length).
  - Home advantage: 50 ELO points added to the home team's rating for the
    purpose of computing expected win probability only. The stored ELO values
    are the raw ratings without home advantage.
  - Season regression: At the start of each new season, each team's ELO is
    regressed 25% toward 1500:
        new_elo = 0.75 * old_elo + 0.25 * 1500
    This prevents compounding of historical advantage over years.
  - Draws: treated as 0.5 outcome for both teams.
  - Incomplete matches: ELO is not updated until a result is recorded
    (is_complete must be True for a match to update ratings).

Leakage policy:
  The pre-match ELO snapshot for match M is computed from all matches
  with match_time < M.match_time that have a recorded result.
  Matches without match_time are processed last within their season/round.
"""

from __future__ import annotations

from collections import defaultdict

from loguru import logger

from db.models.matches import Match
from features.extractors.base import BaseExtractor

_START_ELO: float = 1500.0
_K_FACTOR: float = 32.0
_HOME_ADVANTAGE: float = 50.0
_REGRESSION_FACTOR: float = 0.75  # keep 75% of prior ELO; 25% regresses to mean


def _expected_win(elo_home: float, elo_away: float, neutral: bool = False) -> float:
    """Expected win probability for home team.

    Applies home advantage only when the team is playing at their actual home
    ground (neutral=False). For Gather Round and other neutral venues, no
    advantage is applied.
    """
    advantage = 0.0 if neutral else _HOME_ADVANTAGE
    return 1.0 / (1.0 + 10.0 ** ((elo_away - (elo_home + advantage)) / 400.0))


def _outcome(result: str | None) -> float | None:
    """Convert result string to numeric outcome for the home team (1/0/0.5)."""
    if result == "home":
        return 1.0
    if result == "away":
        return 0.0
    if result == "draw":
        return 0.5
    return None


class EloExtractor(BaseExtractor):
    """
    Single-pass ELO rating extractor.

    Returns features: home_elo_pre, away_elo_pre, elo_diff.
    """

    def extract(self, matches: list[Match]) -> dict[int, dict]:
        ratings: dict[int, float] = defaultdict(lambda: _START_ELO)
        current_season: int | None = None
        result: dict[int, dict] = {}

        for match in matches:
            # --- Season regression at the start of each new season ---
            if match.season != current_season:
                if current_season is not None:
                    # Regress all tracked ratings toward the mean
                    for team_id in list(ratings.keys()):
                        ratings[team_id] = (
                            _REGRESSION_FACTOR * ratings[team_id]
                            + (1 - _REGRESSION_FACTOR) * _START_ELO
                        )
                current_season = match.season

            home_id = match.home_team_id
            away_id = match.away_team_id
            home_elo = ratings[home_id]
            away_elo = ratings[away_id]

            # Record pre-match snapshot (before this match updates ratings)
            result[match.id] = {
                "home_elo_pre": round(home_elo, 2),
                "away_elo_pre": round(away_elo, 2),
                "elo_diff": round(home_elo - away_elo, 2),
            }

            # Update ratings only for completed matches
            outcome = _outcome(match.result)
            if outcome is None:
                # Incomplete or no result — skip update
                continue

            neutral = getattr(match, "is_neutral_venue", False)
            expected = _expected_win(home_elo, away_elo, neutral=neutral)
            delta = _K_FACTOR * (outcome - expected)
            ratings[home_id] = home_elo + delta
            ratings[away_id] = away_elo - delta

        logger.debug(
            f"EloExtractor: computed ratings for {len(result)} matches "
            f"across {current_season or 'N/A'} seasons."
        )
        return result
