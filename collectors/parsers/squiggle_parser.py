"""
collectors/parsers/squiggle_parser.py
--------------------------------------
Parse and validate raw responses from the Squiggle API.

These are pure functions with no I/O — safe to unit test without any
network calls or database access.

Squiggle API reference: https://api.squiggle.com.au/
Key fields used:
  games:  id, year, round, roundname, hteam, ateam, hteamid, ateamid,
          date, venue, hscore, ascore, winner, complete, is_final
  teams:  id, name, abbrev, state
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from loguru import logger

from collectors.parsers.timezone_utils import squiggle_local_to_utc

# A game with complete >= this value is treated as fully played
_COMPLETE_THRESHOLD = 100


@dataclass
class ParsedGame:
    """Normalised game record ready for database upsert."""
    external_id: str        # str(squiggle game id)
    season: int
    round_number: int
    round_label: str
    home_team_name: str     # canonical name (Squiggle-native)
    away_team_name: str
    home_team_external_id: str   # str(squiggle team id)
    away_team_external_id: str
    match_time: datetime | None  # UTC-aware, None if not scheduled
    venue: str | None
    # Result fields — None until game is complete
    home_score: int | None
    away_score: int | None
    result: str | None           # 'home' | 'away' | 'draw' | None
    is_complete: bool
    is_final: bool
    parse_warnings: list[str] = field(default_factory=list)


@dataclass
class ParsedTeam:
    """Normalised team record."""
    external_id: str    # str(squiggle team id)
    name: str           # canonical Squiggle name
    short_name: str     # abbrev (e.g. 'RICH', 'CAR')
    state: str | None


class SquiggleParseError(ValueError):
    """Raised when a Squiggle response cannot be parsed at all."""


def parse_games(raw: dict) -> list[ParsedGame]:
    """
    Parse the raw Squiggle /games response into a list of ParsedGame objects.

    Skips individual games that fail validation (logs a warning per game).
    Raises SquiggleParseError if the top-level structure is wrong.

    Args:
        raw: Parsed JSON dict from Squiggle /games endpoint.

    Returns:
        List of ParsedGame (may be empty if all games failed validation).
    """
    if not isinstance(raw, dict) or "games" not in raw:
        raise SquiggleParseError(
            "Unexpected Squiggle games response shape: "
            f"{list(raw.keys()) if isinstance(raw, dict) else type(raw)}"
        )

    results: list[ParsedGame] = []
    for i, game in enumerate(raw["games"]):
        try:
            parsed = _parse_single_game(game)
            results.append(parsed)
        except Exception as exc:
            gid = game.get("id", f"index-{i}")
            logger.warning(f"squiggle_parser: skipping game id={gid}: {exc}")

    logger.debug(f"squiggle_parser: parsed {len(results)}/{len(raw['games'])} games.")
    return results


def parse_teams(raw: dict) -> list[ParsedTeam]:
    """
    Parse the raw Squiggle /teams response.

    Raises SquiggleParseError if top-level structure is wrong.
    """
    if not isinstance(raw, dict) or "teams" not in raw:
        raise SquiggleParseError(
            "Unexpected Squiggle teams response shape: "
            f"{list(raw.keys()) if isinstance(raw, dict) else type(raw)}"
        )

    results: list[ParsedTeam] = []
    for team in raw["teams"]:
        try:
            results.append(_parse_single_team(team))
        except Exception as exc:
            logger.warning(f"squiggle_parser: skipping team {team.get('id')}: {exc}")

    logger.debug(f"squiggle_parser: parsed {len(results)} teams.")
    return results


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _parse_single_game(g: dict) -> ParsedGame:
    """Parse one game dict. Raises ValueError on missing required fields."""
    warnings: list[str] = []

    # --- Required fields ---
    game_id = _require_int(g, "id", "game")
    season = _require_int(g, "year", f"game {game_id}")
    round_number = _require_int(g, "round", f"game {game_id}")
    home_team = _require_str(g, "hteam", f"game {game_id}")
    away_team = _require_str(g, "ateam", f"game {game_id}")
    home_team_id = _require_int(g, "hteamid", f"game {game_id}")
    away_team_id = _require_int(g, "ateamid", f"game {game_id}")

    # --- Optional fields ---
    round_label = str(g.get("roundname") or f"Round {round_number}")
    venue = g.get("venue") or None

    # --- Match time ---
    match_time = _parse_match_time(g.get("date"), game_id, warnings)

    # --- Result ---
    complete_pct = int(g.get("complete") or 0)
    is_complete = complete_pct >= _COMPLETE_THRESHOLD
    is_final = bool(int(g.get("is_final") or 0))

    home_score: int | None = None
    away_score: int | None = None
    result: str | None = None

    if is_complete:
        raw_hscore = g.get("hscore")
        raw_ascore = g.get("ascore")
        if raw_hscore is None or raw_ascore is None:
            warnings.append(f"game {game_id}: complete=100 but scores missing.")
        else:
            home_score = int(raw_hscore)
            away_score = int(raw_ascore)
            result = _derive_result(g.get("winner"), home_team, away_team, game_id, warnings)

    return ParsedGame(
        external_id=str(game_id),
        season=season,
        round_number=round_number,
        round_label=round_label,
        home_team_name=home_team,
        away_team_name=away_team,
        home_team_external_id=str(home_team_id),
        away_team_external_id=str(away_team_id),
        match_time=match_time,
        venue=venue,
        home_score=home_score,
        away_score=away_score,
        result=result,
        is_complete=is_complete,
        is_final=is_final,
        parse_warnings=warnings,
    )


def _parse_single_team(t: dict) -> ParsedTeam:
    """Parse one team dict."""
    team_id = _require_int(t, "id", "team")
    name = _require_str(t, "name", f"team {team_id}")
    short_name = str(t.get("abbrev") or name[:4]).upper()
    state = t.get("state") or None
    return ParsedTeam(
        external_id=str(team_id),
        name=name,
        short_name=short_name,
        state=state,
    )


def _parse_match_time(
    raw_date: str | None,
    game_id: int,
    warnings: list[str],
) -> datetime | None:
    """
    Parse Squiggle's date string (AEST/AEDT) → UTC-aware datetime.

    Squiggle returns dates as "YYYY-MM-DD HH:MM:SS" in local Melbourne time.
    Returns None and appends a warning if parsing fails.

    Timezone conversion is handled by timezone_utils.squiggle_local_to_utc.
    """
    if not raw_date:
        warnings.append(f"game {game_id}: no date field.")
        return None
    try:
        return squiggle_local_to_utc(raw_date)
    except (ValueError, TypeError) as exc:
        warnings.append(f"game {game_id}: could not parse date {raw_date!r}: {exc}")
        return None


def _derive_result(
    winner: str | None,
    home_team: str,
    away_team: str,
    game_id: int,
    warnings: list[str],
) -> str | None:
    """Derive 'home' | 'away' | 'draw' from the winner field."""
    if not winner:
        # Empty winner on a complete game = draw
        return "draw"
    if winner == home_team:
        return "home"
    if winner == away_team:
        return "away"
    warnings.append(
        f"game {game_id}: winner={winner!r} matches neither "
        f"home={home_team!r} nor away={away_team!r} — treating as draw."
    )
    return "draw"


def _require_int(d: dict, key: str, context: str) -> int:
    val = d.get(key)
    if val is None:
        raise ValueError(f"Missing required field {key!r} in {context}.")
    try:
        return int(val)
    except (TypeError, ValueError):
        raise ValueError(f"Field {key!r}={val!r} is not an int in {context}.")


def _require_str(d: dict, key: str, context: str) -> str:
    val = d.get(key)
    if not val:
        raise ValueError(f"Missing required string field {key!r} in {context}.")
    return str(val).strip()
