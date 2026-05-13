"""
features/extractors/h2h.py
----------------------------
Head-to-head (H2H) feature extractor.

Some AFL matchups are historically lopsided regardless of current form —
the H2H record captures rivalry dynamics that ELO and rolling form miss.

Features produced (per match, from the home team's perspective):
  - h2h_home_win_rate_l5:  home team win rate in last 5 meetings vs this away team
                            (None if fewer than 2 prior meetings)
  - h2h_avg_margin_l5:     average point margin for the home team in last 5 meetings
                            positive = home team won by that average margin
                            (None if fewer than 2 prior meetings)
  - h2h_games_played:      number of prior meetings between these two teams
                            used as a reliability indicator (low = treat with caution)

Leakage policy:
  Only completed matches with match_time strictly before the current match
  contribute to a team-pair's rolling window.  The window is computed from
  the ordered match list, which is already sorted chronologically.

Design note:
  H2H is directional: A vs B and B vs A are tracked separately (reflecting
  home/away effects) but the L5 window is over whichever team played at home,
  so flipping home/away does not combine records — each direction uses
  the last 5 meetings where *that* combination appeared in that order.
  This is intentional: it captures venue-specific H2H advantage.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass

from loguru import logger

from db.models.matches import Match
from features.extractors.base import BaseExtractor

_WINDOW = 5
_MIN_GAMES_FOR_RATE = 2   # require at least 2 meetings before emitting a rate


@dataclass
class _H2HRecord:
    """One completed H2H meeting from the home team's perspective."""
    margin: int   # home_score - away_score; positive = home won


class H2HExtractor(BaseExtractor):
    """
    Head-to-head feature extractor.

    Tracks per-(home_team_id, away_team_id) deques and emits win rate and
    average margin for the last _WINDOW meetings.
    """

    def extract(self, matches: list[Match]) -> dict[int, dict]:
        # (home_team_id, away_team_id) → deque of last _WINDOW H2H records
        history: dict[tuple[int, int], deque[_H2HRecord]] = defaultdict(
            lambda: deque(maxlen=_WINDOW)
        )
        # (home_team_id, away_team_id) → total games ever played (all history)
        total_played: dict[tuple[int, int], int] = defaultdict(int)

        result: dict[int, dict] = {}

        for match in matches:
            pair = (match.home_team_id, match.away_team_id)
            window = history[pair]
            played = total_played[pair]

            # Emit pre-match features
            result[match.id] = _h2h_features(window, played)

            # Update only for completed matches with scores
            if not match.result or match.home_score is None or match.away_score is None:
                continue

            margin = match.home_score - match.away_score
            window.append(_H2HRecord(margin=margin))
            total_played[pair] += 1

        logger.debug(f"H2HExtractor: computed H2H features for {len(result)} matches.")
        return result


def _h2h_features(window: deque[_H2HRecord], total_played: int) -> dict:
    """Compute H2H features from a (home_team, away_team) pair's deque."""
    n = len(window)
    if n < _MIN_GAMES_FOR_RATE:
        return {
            "h2h_home_win_rate_l5": None,
            "h2h_avg_margin_l5": None,
            "h2h_games_played": total_played,
        }
    wins = sum(1 for g in window if g.margin > 0)
    avg_margin = sum(g.margin for g in window) / n
    return {
        "h2h_home_win_rate_l5": round(wins / n, 4),
        "h2h_avg_margin_l5": round(avg_margin, 2),
        "h2h_games_played": total_played,
    }
