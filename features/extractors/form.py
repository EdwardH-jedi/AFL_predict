"""
features/extractors/form.py
-----------------------------
Rolling form extractor.

Computes rolling per-team performance statistics over the last N completed
games prior to each match. Features are computed from the team's perspective
(i.e. home team features use the home team's last N games regardless of
whether they were home or away in those prior games).

Features produced:
  - home_win_rate_l{N}:        fraction of last N games the home team won
  - home_avg_pts_for_l{N}:     average points scored by the home team
  - home_avg_pts_against_l{N}: average points conceded by the home team
  - away_win_rate_l{N}:        same for the away team
  - away_avg_pts_for_l{N}:     ...
  - away_avg_pts_against_l{N}: ...

Leakage policy:
  Only games with match_time < current match's match_time and is_complete=True
  contribute to a team's rolling window. Matches without match_time are
  processed last within their position in the sorted list and therefore
  correctly see all earlier results.

If a team has fewer than N completed prior games the available window is used
(values are not None — partial windows are valid). If a team has zero prior
games all form features are None.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass

from loguru import logger

from db.models.matches import Match
from features.extractors.base import BaseExtractor

_DEFAULT_WINDOW: int = 10


@dataclass
class _GameRecord:
    """Minimal record of one completed game from a team's perspective."""
    pts_for: int
    pts_against: int
    won: bool  # True if this team won; False for loss or draw


class FormExtractor(BaseExtractor):
    """
    Rolling form feature extractor.

    Args:
        window: Number of prior completed games to include in the rolling window.
    """

    def __init__(self, window: int = _DEFAULT_WINDOW) -> None:
        self._window = window
        self._suffix = f"l{window}"

    def extract(self, matches: list[Match]) -> dict[int, dict]:
        # Per-team rolling deque of the last `window` completed games
        history: dict[int, deque[_GameRecord]] = defaultdict(
            lambda: deque(maxlen=self._window)
        )
        result: dict[int, dict] = {}

        for match in matches:
            home_id = match.home_team_id
            away_id = match.away_team_id

            # Snapshot pre-match form for both teams
            result[match.id] = {
                **self._form_features("home", history[home_id]),
                **self._form_features("away", history[away_id]),
            }

            # Update history only for completed matches with scores
            if not match.result or match.home_score is None or match.away_score is None:
                continue

            home_won = match.result == "home"
            away_won = match.result == "away"

            history[home_id].append(_GameRecord(
                pts_for=match.home_score,
                pts_against=match.away_score,
                won=home_won,
            ))
            history[away_id].append(_GameRecord(
                pts_for=match.away_score,
                pts_against=match.home_score,
                won=away_won,
            ))

        logger.debug(
            f"FormExtractor(window={self._window}): "
            f"computed features for {len(result)} matches."
        )
        return result

    def _form_features(self, side: str, window: deque[_GameRecord]) -> dict:
        """Compute rolling stats from a team's recent game deque."""
        s = self._suffix
        if not window:
            return {
                f"{side}_win_rate_{s}": None,
                f"{side}_avg_pts_for_{s}": None,
                f"{side}_avg_pts_against_{s}": None,
            }
        n = len(window)
        wins = sum(1 for g in window if g.won)
        pts_for = sum(g.pts_for for g in window)
        pts_against = sum(g.pts_against for g in window)
        return {
            f"{side}_win_rate_{s}": round(wins / n, 4),
            f"{side}_avg_pts_for_{s}": round(pts_for / n, 2),
            f"{side}_avg_pts_against_{s}": round(pts_against / n, 2),
        }
