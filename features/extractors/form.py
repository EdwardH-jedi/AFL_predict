"""
features/extractors/form.py
-----------------------------
Rolling form extractor — multi-window edition.

Computes rolling per-team performance statistics over the last 3, 5, and 10
completed games prior to each match.  All windows are produced in a single
pass over the match list (no redundant iteration).

Features produced:
  Short-term (last 3 games):
  - home_win_rate_l3, away_win_rate_l3

  Medium-term (last 5 games):
  - home_win_rate_l5, away_win_rate_l5

  Standard window (last 10 games):
  - home_win_rate_l10, away_win_rate_l10
  - home_avg_pts_for_l10, away_avg_pts_for_l10
  - home_avg_pts_against_l10, away_avg_pts_against_l10

  Momentum (short-term trend):
  - home_momentum:  home_win_rate_l3 − home_win_rate_l10
                    positive = team is improving, negative = declining
  - away_momentum:  same for away team

Leakage policy:
  Only games with a recorded result and match_time < current match's match_time
  contribute to a team's rolling window (enforced by processing chronologically
  and only updating state after emitting the pre-match snapshot).
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass

from loguru import logger

from db.models.matches import Match
from features.extractors.base import BaseExtractor

_MAX_WINDOW: int = 10
_DEFAULT_WINDOW: int = _MAX_WINDOW

@dataclass
class _GameRecord:
    """One completed game from a team's perspective."""
    pts_for: int
    pts_against: int
    won: bool


class FormExtractor(BaseExtractor):
    """
    Multi-window rolling form feature extractor.

    Maintains a per-team deque of the last _MAX_WINDOW games and derives
    sub-window statistics (L3, L5) from the tail of that deque in O(1).

    The `window` constructor argument is retained for backward compatibility
    but ignored — features for all three windows are always emitted.
    """

    def __init__(self, window: int = _MAX_WINDOW) -> None:
        # window parameter kept for backward compat; always uses _MAX_WINDOW
        self._window = _MAX_WINDOW

    def extract(self, matches: list[Match]) -> dict[int, dict]:
        history: dict[int, deque[_GameRecord]] = defaultdict(
            lambda: deque(maxlen=_MAX_WINDOW)
        )
        result: dict[int, dict] = {}

        for match in matches:
            home_id = match.home_team_id
            away_id = match.away_team_id

            result[match.id] = {
                **_form_features("home", history[home_id]),
                **_form_features("away", history[away_id]),
            }

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
            f"FormExtractor(multi-window): computed features for {len(result)} matches."
        )
        return result


def _win_rate(games: list[_GameRecord]) -> float | None:
    if not games:
        return None
    return round(sum(1 for g in games if g.won) / len(games), 4)


def _form_features(side: str, window: deque[_GameRecord]) -> dict:
    """Compute all form features for one side from its history deque."""
    games = list(window)           # ordered oldest → newest
    n = len(games)

    if n == 0:
        return {
            f"{side}_win_rate_l3": None,
            f"{side}_win_rate_l5": None,
            f"{side}_win_rate_l10": None,
            f"{side}_avg_pts_for_l10": None,
            f"{side}_avg_pts_against_l10": None,
            f"{side}_momentum": None,
        }

    # Sub-window slices from the tail (most recent games)
    l3 = games[max(0, n - 3):]
    l5 = games[max(0, n - 5):]
    l10 = games                    # deque maxlen=10, so this is already ≤10

    wr_l3 = _win_rate(l3)
    wr_l5 = _win_rate(l5)
    wr_l10 = _win_rate(l10)

    pts_for = round(sum(g.pts_for for g in l10) / len(l10), 2)
    pts_against = round(sum(g.pts_against for g in l10) / len(l10), 2)

    # Momentum: short-term minus long-term win rate (None if not enough history)
    momentum: float | None = None
    if wr_l3 is not None and wr_l10 is not None and len(l10) >= 5:
        momentum = round(wr_l3 - wr_l10, 4)

    return {
        f"{side}_win_rate_l3": wr_l3,
        f"{side}_win_rate_l5": wr_l5,
        f"{side}_win_rate_l10": wr_l10,
        f"{side}_avg_pts_for_l10": pts_for,
        f"{side}_avg_pts_against_l10": pts_against,
        f"{side}_momentum": momentum,
    }
