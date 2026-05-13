"""
features/extractors/travel.py
------------------------------
Interstate travel feature extractor.

Perth (WA) and Brisbane/Gold Coast (QLD) teams flying to Melbourne or Sydney
carry a measurable fatigue burden beyond what rest_days captures. A team with
7 days rest having flown from Perth is physiologically different from a team
with 7 days rest at home.

Features produced:
  - home_interstate_travel : 1 if home team's state ≠ venue's state, else 0
  - away_interstate_travel : 1 if away team's state ≠ venue's state, else 0
  - home_travel_km         : approximate km flown by home team (0 if home state)
  - away_travel_km         : approximate km flown by away team (0 if home state)
  - travel_km_diff         : away_travel_km - home_travel_km (positive = away
                             team is more fatigued from travel)

Leakage policy:
  Travel is entirely pre-match information (team state and venue are known
  before the match). No leakage risk.

Implementation:
  Single-pass, stateless. Teams are looked up by name via a Team→state dict.
  Venues are resolved via VENUE_STATE mapping. Unknown teams/venues default
  to 0 (no travel) — conservative assumption.
"""

from __future__ import annotations

from loguru import logger

from collectors.venue_rules import STATE_PAIR_DISTANCE_KM, TEAM_HOME_STATE, VENUE_STATE
from db.models.matches import Match
from db.models.teams import Team
from features.extractors.base import BaseExtractor


class TravelExtractor(BaseExtractor):
    """
    Extracts interstate travel features for each match.

    Resolves team states from the Match model's related Team objects.
    Requires Team objects to be accessible via match.home_team / match.away_team
    relationships, OR uses a pre-built team_id → state lookup.
    """

    def extract(self, matches: list[Match]) -> dict[int, dict]:
        # Build team_id → (name, state) cache from the first pass
        team_state_cache: dict[int, str | None] = {}

        result: dict[int, dict] = {}
        missing_venue = 0
        missing_team = 0

        for match in matches:
            home_id = match.home_team_id
            away_id = match.away_team_id

            # Resolve team states (lazy-populate cache from match relationships)
            if home_id not in team_state_cache:
                team_state_cache[home_id] = _team_state(match, "home")
            if away_id not in team_state_cache:
                team_state_cache[away_id] = _team_state(match, "away")

            home_state = team_state_cache[home_id]
            away_state = team_state_cache[away_id]
            venue_state = _venue_state(match.venue)

            if venue_state is None:
                missing_venue += 1

            if home_state is None or away_state is None:
                missing_team += 1

            home_interstate = _is_interstate(home_state, venue_state)
            away_interstate = _is_interstate(away_state, venue_state)
            home_km = _distance_km(home_state, venue_state) if home_interstate else 0.0
            away_km = _distance_km(away_state, venue_state) if away_interstate else 0.0

            result[match.id] = {
                "home_interstate_travel": int(home_interstate),
                "away_interstate_travel": int(away_interstate),
                "home_travel_km": home_km,
                "away_travel_km": away_km,
                "travel_km_diff": round(away_km - home_km, 1),
            }

        if missing_venue:
            logger.debug(
                f"TravelExtractor: {missing_venue} matches with unknown venue state "
                "(defaulting to no interstate travel)."
            )
        if missing_team:
            logger.debug(
                f"TravelExtractor: {missing_team} matches with unknown team state."
            )
        logger.debug(
            f"TravelExtractor: processed {len(result)} matches."
        )
        return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _team_state(match: Match, side: str) -> str | None:
    """
    Look up a team's home state. Tries relationship objects first, falls back
    to name-based lookup via TEAM_HOME_STATE.
    """
    # Try SQLAlchemy relationship
    team_obj: Team | None = getattr(match, f"{side}_team", None)
    if team_obj is not None and hasattr(team_obj, "name"):
        state = TEAM_HOME_STATE.get(team_obj.name)
        if state:
            return state

    # Relationship not loaded — nothing we can do without a DB call
    return None


def _venue_state(venue: str | None) -> str | None:
    if not venue:
        return None
    if venue in VENUE_STATE:
        return VENUE_STATE[venue]
    # Fuzzy partial match
    venue_lower = venue.lower()
    for key, state in VENUE_STATE.items():
        if key.lower() in venue_lower or venue_lower in key.lower():
            return state
    return None


def _is_interstate(team_state: str | None, venue_state: str | None) -> bool:
    if team_state is None or venue_state is None:
        return False
    return team_state != venue_state


def _distance_km(team_state: str | None, venue_state: str | None) -> float:
    if team_state is None or venue_state is None or team_state == venue_state:
        return 0.0
    pair = frozenset({team_state, venue_state})
    return STATE_PAIR_DISTANCE_KM.get(pair, 1500.0)  # 1500 km fallback
