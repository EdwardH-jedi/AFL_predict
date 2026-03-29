"""
collectors/transformers/odds_transformer.py
--------------------------------------------
Convert validated odds event records into plain dicts suitable for
constructing OddsSnapshot model instances.

Also owns the implied probability calculation — this is a derived field
computed at write time, not stored in the source payload.

Pure functions — no I/O, no database access.
"""

from __future__ import annotations

from datetime import datetime

from collectors.parsers.odds_parser import ParsedOddsEvent


def odds_event_to_snapshot_kwargs(
    event: ParsedOddsEvent,
    match_id: int,
    snapshot_time: datetime,
    snapshot_type: str = "scheduled",
) -> dict:
    """
    Convert a validated ParsedOddsEvent into keyword arguments for
    OddsSnapshot(**kwargs).

    Computes implied probabilities from the decimal odds during transformation.
    Raises ValueError if odds are invalid (caller should validate first).

    Args:
        event:         Validated ParsedOddsEvent.
        match_id:      DB primary key of the matched Match row.
        snapshot_time: UTC datetime when this snapshot was taken.
        snapshot_type: 'opening' | 'closing' | 'scheduled' (default).
    """
    home_prob, away_prob, overround = _implied_probs(event.home_odds, event.away_odds)

    return {
        "match_id": match_id,
        "bookmaker": event.bookmaker_key,
        "home_odds": event.home_odds,
        "away_odds": event.away_odds,
        "home_implied_prob": home_prob,
        "away_implied_prob": away_prob,
        "overround": overround,
        "snapshot_time": snapshot_time,
        "snapshot_type": snapshot_type,
    }


def odds_event_to_update_kwargs(
    event: ParsedOddsEvent,
    snapshot_time: datetime,
) -> dict:
    """
    Return only the fields that should be updated on an existing OddsSnapshot row
    when a same-day duplicate is detected (idempotent update path).

    Does not include match_id, bookmaker, or snapshot_type — those are the
    identity fields and must not change on an update.
    """
    home_prob, away_prob, overround = _implied_probs(event.home_odds, event.away_odds)

    return {
        "home_odds": event.home_odds,
        "away_odds": event.away_odds,
        "home_implied_prob": home_prob,
        "away_implied_prob": away_prob,
        "overround": overround,
        "snapshot_time": snapshot_time,
    }


# ---------------------------------------------------------------------------
# Internal math utilities
# ---------------------------------------------------------------------------

def _implied_probs(
    home_odds: float, away_odds: float
) -> tuple[float, float, float]:
    """
    Convert decimal odds to overround-normalised implied probabilities.

    Returns (home_prob, away_prob, overround).
    Overround > 1.0 represents bookmaker margin.

    Raises ValueError if either odds value is <= 1.0.
    """
    if home_odds <= 1.0 or away_odds <= 1.0:
        raise ValueError(
            f"Odds must be > 1.0 for probability conversion "
            f"(got home={home_odds}, away={away_odds})."
        )
    raw_home = 1.0 / home_odds
    raw_away = 1.0 / away_odds
    overround = raw_home + raw_away
    home_prob = raw_home / overround
    away_prob = raw_away / overround
    return round(home_prob, 6), round(away_prob, 6), round(overround, 6)
