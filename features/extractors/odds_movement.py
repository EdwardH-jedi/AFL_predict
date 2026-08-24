"""
features/extractors/odds_movement.py
--------------------------------------
Odds movement feature extractor.

Captures how bookmaker odds have *moved* between the opening snapshot and the
latest pre-match snapshot for each match.  A sharp line move (odds shortening
on one side) is one of the strongest publicly-available signals that informed
money has entered the market.

Features produced per match:
  - bm_home_odds_open    : earliest recorded home odds (pre-match)
  - bm_away_odds_open    : earliest recorded away odds (pre-match)
  - bm_home_odds_drift   : (latest - open) / open  — positive = home drifting out
  - bm_away_odds_drift   : (latest - open) / open  — positive = away drifting out
  - bm_line_move         : 'home_shorten' | 'away_shorten' | 'stable' | 'unknown'
                           home_shorten  → home odds fell >2%  (market backing home)
                           away_shorten  → away odds fell >2%  (market backing away)
                           stable        → neither side moved >2%
                           unknown       → only one snapshot available

Leakage policy:
  Only snapshots with snapshot_time < match.match_time are used.
  Matches without match_time return None for all features.

Requires a SQLAlchemy Session (same pattern as BookmakerExtractor).
"""

from __future__ import annotations

from loguru import logger
from sqlalchemy.orm import Session

from db.models.matches import Match
from db.models.odds_snapshots import OddsSnapshot
from features.extractors.base import BaseExtractor

# Threshold below which odds movement is considered "stable" (2%)
_MOVE_THRESHOLD = 0.02

_NULL_FEATURES: dict = {
    "bm_home_odds_open": None,
    "bm_away_odds_open": None,
    "bm_home_odds_drift": None,
    "bm_away_odds_drift": None,
    "bm_line_move": None,
}


class OddsMovementExtractor(BaseExtractor):
    """
    Extracts opening vs latest odds drift from the odds_snapshots table.

    Requires a SQLAlchemy Session to query historical snapshots.
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    def extract(self, matches: list[Match]) -> dict[int, dict]:
        result: dict[int, dict] = {}
        found_movement = 0
        single_snapshot = 0

        for match in matches:
            if match.match_time is None:
                result[match.id] = dict(_NULL_FEATURES)
                continue

            # Load all pre-match snapshots ordered by time
            snapshots: list[OddsSnapshot] = (
                self._db.query(OddsSnapshot)
                .filter(OddsSnapshot.match_id == match.id)
                .filter(OddsSnapshot.snapshot_time < match.match_time)
                .order_by(OddsSnapshot.snapshot_time.asc())
                .all()
            )

            if not snapshots:
                result[match.id] = dict(_NULL_FEATURES)
                continue

            opening = snapshots[0]
            latest = snapshots[-1]

            open_home = opening.home_odds
            open_away = opening.away_odds
            latest_home = latest.home_odds
            latest_away = latest.away_odds

            # Need valid odds on both ends to compute drift.
            # Written as explicit `is None` disjunction rather than
            # `None in (...)` so the type checker narrows all four to float.
            if (
                open_home is None
                or open_away is None
                or latest_home is None
                or latest_away is None
            ):
                result[match.id] = dict(_NULL_FEATURES)
                continue

            if len(snapshots) == 1:
                # Only one snapshot — cannot compute movement
                single_snapshot += 1
                result[match.id] = {
                    "bm_home_odds_open": round(open_home, 4),
                    "bm_away_odds_open": round(open_away, 4),
                    "bm_home_odds_drift": 0.0,
                    "bm_away_odds_drift": 0.0,
                    "bm_line_move": "unknown",
                }
                continue

            # Drift = (latest - open) / open
            # Negative drift = odds shortened (market backing that side)
            home_drift = (latest_home - open_home) / open_home
            away_drift = (latest_away - open_away) / open_away

            # Classify line move direction
            home_shorten = home_drift < -_MOVE_THRESHOLD
            away_shorten = away_drift < -_MOVE_THRESHOLD

            if home_shorten and not away_shorten:
                line_move = "home_shorten"
            elif away_shorten and not home_shorten:
                line_move = "away_shorten"
            elif home_shorten and away_shorten:
                # Both shortened — unusual (overround tightening), classify by magnitude
                line_move = "home_shorten" if home_drift < away_drift else "away_shorten"
            else:
                line_move = "stable"

            found_movement += 1 if line_move != "stable" else 0
            result[match.id] = {
                "bm_home_odds_open": round(open_home, 4),
                "bm_away_odds_open": round(open_away, 4),
                "bm_home_odds_drift": round(home_drift, 6),
                "bm_away_odds_drift": round(away_drift, 6),
                "bm_line_move": line_move,
            }

        logger.debug(
            f"OddsMovementExtractor: {found_movement} matches with significant line moves, "
            f"{single_snapshot} with single snapshot only."
        )
        return result
