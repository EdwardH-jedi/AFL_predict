"""
features/extractors/player_availability.py
--------------------------------------------
Player availability feature extractor.

For each match, looks up the PlayerLineup records for both teams and
exposes availability indicators as pre-match features.

Features produced:
  - home_availability_index  : 0.0-1.0; 1.0 = full strength (default 1.0 if unknown)
  - away_availability_index  : 0.0-1.0; 1.0 = full strength (default 1.0 if unknown)
  - home_key_players_absent  : count of top-5 players not in lineup (0 if unknown)
  - away_key_players_absent  : count of top-5 players not in lineup (0 if unknown)
  - availability_diff        : home_index - away_index (positive = home has advantage)

Leakage policy:
  PlayerLineup.announced_at is checked: we only use lineups announced before
  match_time.  If announced_at is NULL (historical data from AFL Tables), the
  lineup is treated as always available (historical, not a future leak).
  If no lineup exists, defaults of 1.0 / 0 / 0 are used so downstream models
  are not disrupted by missing data.

Requires a SQLAlchemy Session (same pattern as BookmakerExtractor).
"""

from __future__ import annotations

from loguru import logger
from sqlalchemy.orm import Session

from db.models.matches import Match
from db.models.player_lineups import PlayerLineup
from features.extractors.base import BaseExtractor

_DEFAULT_AVAIL = 1.0   # assume full strength when no data
_DEFAULT_ABSENT = 0    # assume no key absences when no data

_NULL_FEATURES: dict = {
    "home_availability_index": _DEFAULT_AVAIL,
    "away_availability_index": _DEFAULT_AVAIL,
    "home_key_players_absent": _DEFAULT_ABSENT,
    "away_key_players_absent": _DEFAULT_ABSENT,
    "availability_diff": 0.0,
}


class PlayerAvailabilityExtractor(BaseExtractor):
    """
    Extracts pre-match player availability indicators from PlayerLineup records.

    Requires a SQLAlchemy Session to query the player_lineups table.
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    def extract(self, matches: list[Match]) -> dict[int, dict]:
        result: dict[int, dict] = {}
        found = 0
        partial = 0

        for match in matches:
            home_lineup = self._get_lineup(match.id, match.home_team_id, match.match_time)
            away_lineup = self._get_lineup(match.id, match.away_team_id, match.match_time)

            if home_lineup is None and away_lineup is None:
                result[match.id] = dict(_NULL_FEATURES)
                continue

            home_avail = _avail(home_lineup)
            away_avail = _avail(away_lineup)
            home_absent = _absent(home_lineup)
            away_absent = _absent(away_lineup)

            if home_lineup is not None and away_lineup is not None:
                found += 1
            else:
                partial += 1

            result[match.id] = {
                "home_availability_index": round(home_avail, 4),
                "away_availability_index": round(away_avail, 4),
                "home_key_players_absent": home_absent,
                "away_key_players_absent": away_absent,
                "availability_diff": round(home_avail - away_avail, 4),
            }

        logger.debug(
            f"PlayerAvailabilityExtractor: {found} full, {partial} partial, "
            f"{len(matches) - found - partial} missing."
        )
        return result

    def _get_lineup(
        self,
        match_id: int,
        team_id: int,
        match_time,
    ) -> PlayerLineup | None:
        """
        Fetch the pre-match lineup for a team, respecting leakage policy.

        If announced_at is NULL (historical data), always include it.
        If announced_at is set, only include if announced_at < match_time.
        """
        query = (
            self._db.query(PlayerLineup)
            .filter(PlayerLineup.match_id == match_id)
            .filter(PlayerLineup.team_id == team_id)
        )

        # Filter by announcement time if available and match_time is known
        if match_time is not None:
            # Include rows where announced_at is NULL (historical) OR before match_time
            from sqlalchemy import or_
            query = query.filter(
                or_(
                    PlayerLineup.announced_at.is_(None),
                    PlayerLineup.announced_at < match_time,
                )
            )

        return query.first()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _avail(lineup: PlayerLineup | None) -> float:
    if lineup is None or lineup.availability_index is None:
        return _DEFAULT_AVAIL
    return float(lineup.availability_index)


def _absent(lineup: PlayerLineup | None) -> int:
    if lineup is None or lineup.key_players_absent is None:
        return _DEFAULT_ABSENT
    return int(lineup.key_players_absent)
