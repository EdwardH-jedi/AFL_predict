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

    def __init__(self, db: Session, allow_unknown_announcement: bool = False) -> None:
        """
        Args:
            db: session.
            allow_unknown_announcement: admit lineups with a NULL `announced_at`.
                Off by default. Historical rows carry no announcement time and
                are derived from who actually played, which is post-match
                information. Enable only for explicitly retrospective analysis.
        """
        self._db = db
        self._allow_unknown_announcement = allow_unknown_announcement
        self._excluded_not_as_of = 0

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

        Only lineups demonstrably announced before kickoff are used:
        `announced_at` must be present AND earlier than `match_time`.

        A NULL `announced_at` is excluded, not admitted. Historical AFL Tables
        rows carry no announcement time and are in practice derived from who
        actually played, which is precisely the post-match information a
        pre-match feature must not see. Treating unknown as safe was fail-open;
        this is fail-closed. Pass `allow_unknown_announcement=True` to opt back
        in for explicitly retrospective analysis.
        """
        query = (
            self._db.query(PlayerLineup)
            .filter(PlayerLineup.match_id == match_id)
            .filter(PlayerLineup.team_id == team_id)
        )

        # Fail closed: require a known announcement time strictly before kickoff.
        if match_time is None:
            # No kickoff time means the boundary cannot be evaluated at all.
            self._excluded_not_as_of += 1
            return None

        if self._allow_unknown_announcement:
            from sqlalchemy import or_
            query = query.filter(
                or_(
                    PlayerLineup.announced_at.is_(None),
                    PlayerLineup.announced_at < match_time,
                )
            )
        else:
            query = query.filter(
                PlayerLineup.announced_at.isnot(None),
                PlayerLineup.announced_at < match_time,
            )

        row = query.first()
        if row is None:
            self._excluded_not_as_of += 1
        return row


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
