"""
collectors/transformers/afl_transformer.py
-------------------------------------------
Convert validated AFL dataclass records into plain dicts suitable for
constructing SQLAlchemy model instances.

Transformers are pure functions — no I/O, no database access.
They accept validated ParsedGame / ParsedTeam objects and return kwargs
dicts ready for  Match(**kwargs)  or  Team(**kwargs).

Why a separate layer?
  Keeps the upsert logic in ingest_afl.py free of field-mapping details.
  Field renaming or additions only need to change the transformer, not the
  ingest job.
"""

from __future__ import annotations

from collectors.parsers.squiggle_parser import ParsedGame, ParsedTeam


def team_to_kwargs(team: ParsedTeam) -> dict:
    """
    Convert a validated ParsedTeam into keyword arguments for Team(**kwargs).

    All fields that may be updated on subsequent ingestion runs are included,
    so callers can do both insert and update from the same dict.
    """
    return {
        "name": team.name,
        "short_name": team.short_name,
        "state": team.state,
        "external_id": team.external_id,
    }


def game_to_match_kwargs(
    game: ParsedGame,
    home_team_id: int,
    away_team_id: int,
) -> dict:
    """
    Convert a validated ParsedGame into keyword arguments for Match(**kwargs).

    Result fields (home_score, away_score, result) are only populated when
    is_complete=True — callers must not set them otherwise to avoid writing
    partial data that could mislead the settle_results job.

    Args:
        game:         Validated ParsedGame from squiggle_parser.
        home_team_id: DB primary key of the home Team row.
        away_team_id: DB primary key of the away Team row.
    """
    kwargs: dict = {
        "season": game.season,
        "round_number": game.round_number,
        "round_label": game.round_label,
        "home_team_id": home_team_id,
        "away_team_id": away_team_id,
        "match_time": game.match_time,
        "venue": game.venue,
        "external_id": game.external_id,
        "is_final": game.is_final,
    }

    if game.is_complete:
        kwargs["home_score"] = game.home_score
        kwargs["away_score"] = game.away_score
        kwargs["result"] = game.result
    else:
        kwargs["home_score"] = None
        kwargs["away_score"] = None
        kwargs["result"] = None

    return kwargs


def game_to_result_kwargs(game: ParsedGame) -> dict | None:
    """
    Return only the result fields from a completed game, for updating
    an existing Match row.

    Returns None if the game is not yet complete.
    """
    if not game.is_complete:
        return None
    return {
        "home_score": game.home_score,
        "away_score": game.away_score,
        "result": game.result,
    }


def game_to_schedule_kwargs(game: ParsedGame) -> dict:
    """
    Return only the mutable scheduling fields (time, venue, label).

    Used when updating an existing match whose identity fields must not change.
    """
    return {
        "match_time": game.match_time,
        "venue": game.venue,
        "round_label": game.round_label,
    }
