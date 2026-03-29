"""
collectors/validators/afl_validator.py
---------------------------------------
Business-rule validation for parsed AFL game and team records.

This layer sits between parsing (structure checks) and transformation
(DB-ready conversion). It enforces domain-level invariants that parsers
should not need to know about.

Functions return ValidationResult rather than raising, so callers can
decide whether to skip, warn, or abort.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from collectors.parsers.squiggle_parser import ParsedGame, ParsedTeam

# Valid AFL season range. Adjust upper bound as needed.
_SEASON_MIN = 1897
_SEASON_MAX = 2035

# Rounds 1–27 regular season + up to 4 finals rounds = safe upper bound.
_ROUND_MIN = 1
_ROUND_MAX = 30

# Score sanity bounds. AFL scores outside this range are extraordinary.
_SCORE_MIN = 0
_SCORE_MAX = 250


@dataclass
class ValidationResult:
    """
    Outcome of a validation check.

    is_valid is False if any hard error is present.
    Warnings are informational — the record is still written.
    """
    is_valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.is_valid

    def summary(self) -> str:
        parts = []
        if self.errors:
            parts.append(f"ERRORS: {'; '.join(self.errors)}")
        if self.warnings:
            parts.append(f"WARNINGS: {'; '.join(self.warnings)}")
        return " | ".join(parts) if parts else "OK"


def validate_game(game: ParsedGame) -> ValidationResult:
    """
    Validate a ParsedGame against AFL business rules.

    Hard errors (is_valid=False):
      - Season out of expected range
      - Round number out of expected range
      - Home and away team are the same

    Warnings (is_valid=True but flagged):
      - No match time scheduled
      - Complete flag set but result/scores are absent
      - Scores outside plausible AFL range
    """
    errors: list[str] = []
    warnings: list[str] = []

    # --- Hard errors ---
    if not (_SEASON_MIN <= game.season <= _SEASON_MAX):
        errors.append(
            f"Season {game.season} is outside the valid range "
            f"[{_SEASON_MIN}, {_SEASON_MAX}]."
        )

    if not (_ROUND_MIN <= game.round_number <= _ROUND_MAX):
        errors.append(
            f"Round {game.round_number} is outside the valid range "
            f"[{_ROUND_MIN}, {_ROUND_MAX}]."
        )

    if game.home_team_name == game.away_team_name:
        errors.append(
            f"Home and away team are identical: {game.home_team_name!r}."
        )

    if not game.external_id:
        errors.append("external_id is empty — cannot upsert without a stable key.")

    # --- Warnings ---
    if game.match_time is None:
        warnings.append("No match_time — scheduling and ordering may be incorrect.")

    if game.is_complete:
        if game.result is None:
            warnings.append("is_complete=True but result is None.")
        if game.home_score is None or game.away_score is None:
            warnings.append("is_complete=True but one or both scores are None.")
        else:
            for label, score in (("home", game.home_score), ("away", game.away_score)):
                if not (_SCORE_MIN <= score <= _SCORE_MAX):
                    warnings.append(
                        f"{label} score {score} is outside plausible range "
                        f"[{_SCORE_MIN}, {_SCORE_MAX}]."
                    )

    if game.is_final and game.round_number < 20:
        warnings.append(
            f"is_final=True but round_number={game.round_number} is unexpectedly low."
        )

    return ValidationResult(is_valid=len(errors) == 0, errors=errors, warnings=warnings)


def validate_team(team: ParsedTeam) -> ValidationResult:
    """
    Validate a ParsedTeam against AFL business rules.

    Hard errors:
      - Name is empty
      - external_id is empty

    Warnings:
      - short_name is empty or unusually long
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not team.name or not team.name.strip():
        errors.append("Team name is empty.")

    if not team.external_id or not team.external_id.strip():
        errors.append("Team external_id is empty — cannot upsert without a stable key.")

    if not team.short_name:
        warnings.append("Team short_name is empty — display may be affected.")
    elif len(team.short_name) > 10:
        warnings.append(
            f"Team short_name {team.short_name!r} is longer than 10 characters."
        )

    return ValidationResult(is_valid=len(errors) == 0, errors=errors, warnings=warnings)
