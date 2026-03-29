"""
features/extractors/venue.py
------------------------------
Venue extractor (stub).

Currently passes the raw venue string through as a categorical feature.
Future iterations could add:
  - Binary home-ground indicator (team plays at their registered home venue)
  - Neutral ground indicator (finals, interstate venues)
  - Historical home/away win rate at this venue

Features produced:
  - venue: Raw venue string from the match record (may be None).
"""

from __future__ import annotations

from loguru import logger

from db.models.matches import Match
from features.extractors.base import BaseExtractor


class VenueExtractor(BaseExtractor):
    """
    Extracts venue information from match records.

    No state is maintained between matches — each row is independent.

    TODO: Expand to home-ground and neutral-ground indicators once team
    home venue data is available in the teams table.
    """

    def extract(self, matches: list[Match]) -> dict[int, dict]:
        result = {
            match.id: {"venue": match.venue}
            for match in matches
        }
        logger.debug(f"VenueExtractor: extracted venue for {len(result)} matches.")
        return result
