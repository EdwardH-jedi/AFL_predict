"""
collectors/validators/odds_validator.py
----------------------------------------
Business-rule validation for parsed odds event records.

Sits between parsing (structural checks) and transformation (DB-ready conversion).
Validates plausibility and internal consistency of odds data beyond what the
parser can confirm from structure alone.
"""

from __future__ import annotations

from collectors.parsers.odds_parser import ParsedOddsEvent
from collectors.validators.afl_validator import ValidationResult

# Decimal odds boundaries for a 2-team H2H market.
# Tight favourites below 1.02 and extreme long-shots above 20.0 are unusual
# for an AFL H2H market and should be flagged even if technically valid.
_ODDS_HARD_MIN = 1.01     # reject below this — data error
_ODDS_HARD_MAX = 50.0     # reject above this — data error
_ODDS_WARN_MIN = 1.05     # warn: extreme favourite
_ODDS_WARN_MAX = 15.0     # warn: extreme long-shot for a 2-team market

# Bookmaker overround (margin) bounds.
# A healthy H2H market has overround between ~1.02 and ~1.15.
_OVERROUND_MIN = 0.95   # below this implies free money — data error
_OVERROUND_MAX = 1.30   # above this implies implausibly large margin


def validate_odds_event(event: ParsedOddsEvent) -> ValidationResult:
    """
    Validate a ParsedOddsEvent against AFL odds business rules.

    Hard errors (is_valid=False):
      - Home or away team name is empty
      - Bookmaker key is empty
      - Either odds value is outside the hard min/max range
      - Overround is outside plausible bounds

    Warnings (is_valid=True but flagged):
      - Odds in the unusual-but-not-impossible range
      - Missing odds_last_update timestamp
    """
    errors: list[str] = []
    warnings: list[str] = []

    # --- Team name presence ---
    if not event.home_team_name or not event.home_team_name.strip():
        errors.append("home_team_name is empty.")
    if not event.away_team_name or not event.away_team_name.strip():
        errors.append("away_team_name is empty.")
    if (
        event.home_team_name
        and event.away_team_name
        and event.home_team_name == event.away_team_name
    ):
        errors.append(
            f"home and away team names are identical: {event.home_team_name!r}."
        )

    # --- Bookmaker ---
    if not event.bookmaker_key or not event.bookmaker_key.strip():
        errors.append("bookmaker_key is empty.")

    # --- Odds range ---
    for label, odds in (("home", event.home_odds), ("away", event.away_odds)):
        if odds < _ODDS_HARD_MIN:
            errors.append(
                f"{label}_odds {odds} is below hard minimum {_ODDS_HARD_MIN}."
            )
        elif odds > _ODDS_HARD_MAX:
            errors.append(
                f"{label}_odds {odds} exceeds hard maximum {_ODDS_HARD_MAX}."
            )
        elif odds < _ODDS_WARN_MIN:
            warnings.append(
                f"{label}_odds {odds} is an extreme favourite "
                f"(< {_ODDS_WARN_MIN}) — verify source."
            )
        elif odds > _ODDS_WARN_MAX:
            warnings.append(
                f"{label}_odds {odds} is an extreme long-shot "
                f"(> {_ODDS_WARN_MAX}) for a 2-team market — verify source."
            )

    # --- Overround sanity (only if odds are individually valid) ---
    if not errors:
        raw_home_ip = 1.0 / event.home_odds
        raw_away_ip = 1.0 / event.away_odds
        overround = raw_home_ip + raw_away_ip

        if overround < _OVERROUND_MIN:
            errors.append(
                f"Overround {overround:.4f} is below {_OVERROUND_MIN} — "
                "implied probabilities sum to less than 1, which indicates a data error."
            )
        elif overround > _OVERROUND_MAX:
            errors.append(
                f"Overround {overround:.4f} exceeds {_OVERROUND_MAX} — "
                "bookmaker margin is implausibly large."
            )

    # --- Timestamp ---
    if event.odds_last_update is None:
        warnings.append("odds_last_update is None — cannot determine odds freshness.")

    return ValidationResult(is_valid=len(errors) == 0, errors=errors, warnings=warnings)
