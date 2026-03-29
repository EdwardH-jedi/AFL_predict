"""
tests/test_validators.py
-------------------------
Unit tests for the collectors/validators/ layer.

No network calls, no database — pure function testing.
"""

from datetime import datetime, timezone

import pytest

from collectors.parsers.odds_parser import ParsedOddsEvent
from collectors.parsers.squiggle_parser import ParsedGame, ParsedTeam
from collectors.validators.afl_validator import (
    ValidationResult,
    validate_game,
    validate_team,
)
from collectors.validators.odds_validator import validate_odds_event


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _game(**overrides) -> ParsedGame:
    base = ParsedGame(
        external_id="1001",
        season=2025,
        round_number=5,
        round_label="Round 5",
        home_team_name="Richmond",
        away_team_name="Carlton",
        home_team_external_id="14",
        away_team_external_id="3",
        match_time=datetime(2025, 5, 1, 9, 30, tzinfo=timezone.utc),
        venue="MCG",
        home_score=None,
        away_score=None,
        result=None,
        is_complete=False,
        is_final=False,
    )
    for k, v in overrides.items():
        object.__setattr__(base, k, v)
    return base


def _team(**overrides) -> ParsedTeam:
    base = ParsedTeam(
        external_id="14",
        name="Richmond",
        short_name="RICH",
        state="VIC",
    )
    for k, v in overrides.items():
        object.__setattr__(base, k, v)
    return base


def _odds_event(**overrides) -> ParsedOddsEvent:
    base = ParsedOddsEvent(
        external_event_id="event-abc",
        home_team_name="Richmond",
        away_team_name="Carlton",
        commence_time=datetime(2025, 5, 1, 9, 30, tzinfo=timezone.utc),
        bookmaker_key="tab",
        bookmaker_title="TAB",
        home_odds=1.75,
        away_odds=2.10,
        odds_last_update=datetime(2025, 4, 30, 22, 0, tzinfo=timezone.utc),
    )
    for k, v in overrides.items():
        object.__setattr__(base, k, v)
    return base


# ---------------------------------------------------------------------------
# ValidationResult
# ---------------------------------------------------------------------------

class TestValidationResult:
    def test_bool_true_when_valid(self):
        r = ValidationResult(is_valid=True)
        assert bool(r) is True

    def test_bool_false_when_invalid(self):
        r = ValidationResult(is_valid=False, errors=["something wrong"])
        assert bool(r) is False

    def test_summary_ok_when_no_issues(self):
        assert ValidationResult(is_valid=True).summary() == "OK"

    def test_summary_shows_errors(self):
        r = ValidationResult(is_valid=False, errors=["bad season"])
        assert "ERRORS" in r.summary()
        assert "bad season" in r.summary()

    def test_summary_shows_warnings(self):
        r = ValidationResult(is_valid=True, warnings=["no time"])
        assert "WARNINGS" in r.summary()


# ---------------------------------------------------------------------------
# validate_game
# ---------------------------------------------------------------------------

class TestValidateGame:
    def test_valid_fixture_passes(self):
        assert validate_game(_game())

    def test_valid_complete_result_passes(self):
        g = _game(is_complete=True, result="home", home_score=102, away_score=89)
        assert validate_game(g)

    def test_season_too_low_fails(self):
        result = validate_game(_game(season=1800))
        assert not result
        assert any("Season" in e for e in result.errors)

    def test_season_too_high_fails(self):
        result = validate_game(_game(season=2100))
        assert not result

    def test_round_zero_fails(self):
        result = validate_game(_game(round_number=0))
        assert not result
        assert any("Round" in e for e in result.errors)

    def test_round_too_high_fails(self):
        result = validate_game(_game(round_number=31))
        assert not result

    def test_same_team_both_sides_fails(self):
        g = _game(home_team_name="Richmond", away_team_name="Richmond")
        result = validate_game(g)
        assert not result
        assert any("identical" in e for e in result.errors)

    def test_empty_external_id_fails(self):
        result = validate_game(_game(external_id=""))
        assert not result

    def test_no_match_time_is_warning_not_error(self):
        result = validate_game(_game(match_time=None))
        assert result  # still valid
        assert any("match_time" in w for w in result.warnings)

    def test_complete_missing_result_is_warning(self):
        g = _game(is_complete=True, result=None, home_score=100, away_score=90)
        result = validate_game(g)
        assert result  # valid but warned
        assert any("result is None" in w for w in result.warnings)

    def test_complete_missing_scores_is_warning(self):
        g = _game(is_complete=True, result="home", home_score=None, away_score=None)
        result = validate_game(g)
        assert result
        assert any("scores" in w for w in result.warnings)

    def test_implausible_score_is_warning(self):
        g = _game(is_complete=True, result="home", home_score=300, away_score=89)
        result = validate_game(g)
        assert result  # valid but warned
        assert any("300" in w for w in result.warnings)

    def test_is_final_low_round_is_warning(self):
        g = _game(is_final=True, round_number=3)
        result = validate_game(g)
        assert result  # valid but warned
        assert any("is_final" in w or "round_number" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# validate_team
# ---------------------------------------------------------------------------

class TestValidateTeam:
    def test_valid_team_passes(self):
        assert validate_team(_team())

    def test_empty_name_fails(self):
        result = validate_team(_team(name=""))
        assert not result
        assert any("name" in e for e in result.errors)

    def test_empty_external_id_fails(self):
        result = validate_team(_team(external_id=""))
        assert not result
        assert any("external_id" in e for e in result.errors)

    def test_empty_short_name_is_warning(self):
        result = validate_team(_team(short_name=""))
        assert result  # valid but warned
        assert any("short_name" in w for w in result.warnings)

    def test_long_short_name_is_warning(self):
        result = validate_team(_team(short_name="VERYLONGABBREV"))
        assert result
        assert any("longer than 10" in w for w in result.warnings)

    def test_whitespace_only_name_fails(self):
        result = validate_team(_team(name="   "))
        assert not result


# ---------------------------------------------------------------------------
# validate_odds_event
# ---------------------------------------------------------------------------

class TestValidateOddsEvent:
    def test_valid_event_passes(self):
        assert validate_odds_event(_odds_event())

    def test_empty_home_team_fails(self):
        result = validate_odds_event(_odds_event(home_team_name=""))
        assert not result
        assert any("home_team_name" in e for e in result.errors)

    def test_empty_bookmaker_key_fails(self):
        result = validate_odds_event(_odds_event(bookmaker_key=""))
        assert not result

    def test_same_team_both_sides_fails(self):
        result = validate_odds_event(
            _odds_event(home_team_name="Richmond", away_team_name="Richmond")
        )
        assert not result

    def test_odds_below_hard_min_fails(self):
        result = validate_odds_event(_odds_event(home_odds=0.95))
        assert not result
        assert any("hard minimum" in e for e in result.errors)

    def test_odds_above_hard_max_fails(self):
        result = validate_odds_event(_odds_event(away_odds=60.0))
        assert not result
        assert any("hard maximum" in e for e in result.errors)

    def test_extreme_favourite_is_warning(self):
        result = validate_odds_event(_odds_event(home_odds=1.02, away_odds=10.0))
        assert result  # valid but warned
        assert any("favourite" in w for w in result.warnings)

    def test_extreme_longshot_is_warning(self):
        result = validate_odds_event(_odds_event(home_odds=1.10, away_odds=16.0))
        assert result
        assert any("long-shot" in w for w in result.warnings)

    def test_implausible_overround_low_fails(self):
        # odds that imply probabilities summing to < 0.95 (free money)
        result = validate_odds_event(_odds_event(home_odds=2.20, away_odds=2.20))
        assert not result
        assert any("Overround" in e for e in result.errors)

    def test_overround_high_fails(self):
        # extreme margin
        result = validate_odds_event(_odds_event(home_odds=1.10, away_odds=1.10))
        assert not result
        assert any("Overround" in e for e in result.errors)

    def test_null_last_update_is_warning(self):
        result = validate_odds_event(_odds_event(odds_last_update=None))
        assert result
        assert any("odds_last_update" in w for w in result.warnings)

    def test_normal_tab_odds_passes(self):
        # Typical AFL TAB market: ~1.05 overround
        result = validate_odds_event(_odds_event(home_odds=1.75, away_odds=2.10))
        assert result
        assert not result.errors
