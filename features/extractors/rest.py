"""
features/extractors/rest.py
-----------------------------
Rest days extractor.

Computes the number of calendar days between a team's previous match and
the current match. "Rest days" is a proxy for physical recovery and fatigue.

Features produced:
  - home_rest_days: days since home team's previous match (None if first match)
  - away_rest_days: days since away team's previous match (None if first match)

Leakage policy:
  Only matches with match_time < current match's match_time are considered
  as prior matches. No result information is used — only the date.
  Matches without match_time are assigned None for rest_days.
"""

from __future__ import annotations

from datetime import datetime

from loguru import logger

from db.models.matches import Match
from features.extractors.base import BaseExtractor


class RestDaysExtractor(BaseExtractor):
    """
    Single-pass rest days extractor.

    Processes matches in chronological order, tracking the last match date
    per team. For each match, records the gap since the team's prior game.
    """

    def extract(self, matches: list[Match]) -> dict[int, dict]:
        last_match_time: dict[int, datetime] = {}
        result: dict[int, dict] = {}

        for match in matches:
            home_id = match.home_team_id
            away_id = match.away_team_id

            if match.match_time is None:
                result[match.id] = {
                    "home_rest_days": None,
                    "away_rest_days": None,
                }
                continue

            current_time = match.match_time

            # Compute rest days for each team
            home_rest = _days_between(last_match_time.get(home_id), current_time)
            away_rest = _days_between(last_match_time.get(away_id), current_time)

            result[match.id] = {
                "home_rest_days": home_rest,
                "away_rest_days": away_rest,
            }

            # Update last-seen time for both teams
            last_match_time[home_id] = current_time
            last_match_time[away_id] = current_time

        logger.debug(
            f"RestDaysExtractor: computed rest days for {len(result)} matches."
        )
        return result


def _days_between(prior: datetime | None, current: datetime) -> int | None:
    """
    Return the number of whole calendar days between two datetimes.

    Returns None if prior is None (team's first recorded match).

    Strips tzinfo before subtraction: SQLite returns naive datetimes, but
    some rows may have been created with UTC-aware datetimes (e.g. from
    a different ingestion path). Normalising both to naive prevents
    TypeError: can't compare offset-naive and offset-aware datetimes.
    """
    if prior is None:
        return None
    # Strip tzinfo from both so subtraction works regardless of source
    p = prior.replace(tzinfo=None)
    c = current.replace(tzinfo=None)
    delta = c - p
    return max(0, delta.days)
