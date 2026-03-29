"""
features/extractors/bookmaker.py
----------------------------------
Bookmaker implied-probability extractor.

For each match, looks up the *latest* odds snapshot with a snapshot_time
that is strictly before the match's match_time. This enforces the leakage
policy: we only use odds information that was available before the game started.

If no pre-match snapshot exists (e.g. odds not collected for this game) all
bookmaker features are returned as None.

Features produced:
  - bm_home_odds
  - bm_away_odds
  - bm_home_implied_prob
  - bm_away_implied_prob
  - bm_overround

Leakage policy:
  snapshot_time < match.match_time is enforced in the DB query.
  Matches without match_time return None for all bookmaker features.
"""

from __future__ import annotations

from loguru import logger
from sqlalchemy.orm import Session

from db.models.matches import Match
from db.models.odds_snapshots import OddsSnapshot
from features.extractors.base import BaseExtractor

_NULL_FEATURES: dict = {
    "bm_home_odds": None,
    "bm_away_odds": None,
    "bm_home_implied_prob": None,
    "bm_away_implied_prob": None,
    "bm_overround": None,
}


class BookmakerExtractor(BaseExtractor):
    """
    Extracts pre-match bookmaker implied probabilities from odds snapshots.

    Requires a SQLAlchemy Session to query the odds_snapshots table.
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    def extract(self, matches: list[Match]) -> dict[int, dict]:
        result: dict[int, dict] = {}
        found = 0

        for match in matches:
            if match.match_time is None:
                result[match.id] = dict(_NULL_FEATURES)
                continue

            snapshot: OddsSnapshot | None = (
                self._db.query(OddsSnapshot)
                .filter(OddsSnapshot.match_id == match.id)
                .filter(OddsSnapshot.snapshot_time < match.match_time)
                .order_by(OddsSnapshot.snapshot_time.desc())
                .first()
            )

            if snapshot is None:
                result[match.id] = dict(_NULL_FEATURES)
                continue

            found += 1
            result[match.id] = {
                "bm_home_odds": snapshot.home_odds,
                "bm_away_odds": snapshot.away_odds,
                "bm_home_implied_prob": snapshot.home_implied_prob,
                "bm_away_implied_prob": snapshot.away_implied_prob,
                "bm_overround": snapshot.overround,
            }

        logger.debug(
            f"BookmakerExtractor: {found}/{len(matches)} matches have pre-match odds."
        )
        return result
