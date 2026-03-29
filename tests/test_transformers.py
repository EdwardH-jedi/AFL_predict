"""
tests/test_transformers.py
---------------------------
Unit tests for the collectors/transformers/ layer.

No network calls, no database — pure function testing.
"""

from datetime import datetime, timezone

import pytest

from collectors.parsers.odds_parser import ParsedOddsEvent
from collectors.parsers.squiggle_parser import ParsedGame, ParsedTeam
from collectors.transformers.afl_transformer import (
    game_to_match_kwargs,
    game_to_result_kwargs,
    game_to_schedule_kwargs,
    team_to_kwargs,
)
from collectors.transformers.odds_transformer import (
    _implied_probs,
    odds_event_to_snapshot_kwargs,
    odds_event_to_update_kwargs,
)

_NOW = datetime(2025, 5, 1, 9, 0, tzinfo=timezone.utc)
_MATCH_TIME = datetime(2025, 5, 1, 9, 30, tzinfo=timezone.utc)


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
        match_time=_MATCH_TIME,
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
        external_id="14", name="Richmond", short_name="RICH", state="VIC"
    )
    for k, v in overrides.items():
        object.__setattr__(base, k, v)
    return base


def _odds_event(**overrides) -> ParsedOddsEvent:
    base = ParsedOddsEvent(
        external_event_id="evt-1",
        home_team_name="Richmond",
        away_team_name="Carlton",
        commence_time=_MATCH_TIME,
        bookmaker_key="tab",
        bookmaker_title="TAB",
        home_odds=1.75,
        away_odds=2.10,
        odds_last_update=_NOW,
    )
    for k, v in overrides.items():
        object.__setattr__(base, k, v)
    return base


# ---------------------------------------------------------------------------
# team_to_kwargs
# ---------------------------------------------------------------------------

class TestTeamToKwargs:
    def test_contains_all_required_fields(self):
        kwargs = team_to_kwargs(_team())
        assert kwargs["name"] == "Richmond"
        assert kwargs["short_name"] == "RICH"
        assert kwargs["state"] == "VIC"
        assert kwargs["external_id"] == "14"

    def test_none_state_preserved(self):
        kwargs = team_to_kwargs(_team(state=None))
        assert kwargs["state"] is None

    def test_returns_dict_not_model(self):
        assert isinstance(team_to_kwargs(_team()), dict)


# ---------------------------------------------------------------------------
# game_to_match_kwargs
# ---------------------------------------------------------------------------

class TestGameToMatchKwargs:
    def test_fixture_has_null_result_fields(self):
        kwargs = game_to_match_kwargs(_game(), home_team_id=1, away_team_id=2)
        assert kwargs["result"] is None
        assert kwargs["home_score"] is None
        assert kwargs["away_score"] is None

    def test_complete_game_includes_result(self):
        g = _game(is_complete=True, result="home", home_score=102, away_score=89)
        kwargs = game_to_match_kwargs(g, home_team_id=1, away_team_id=2)
        assert kwargs["result"] == "home"
        assert kwargs["home_score"] == 102
        assert kwargs["away_score"] == 89

    def test_team_ids_are_passed_through(self):
        kwargs = game_to_match_kwargs(_game(), home_team_id=5, away_team_id=7)
        assert kwargs["home_team_id"] == 5
        assert kwargs["away_team_id"] == 7

    def test_external_id_is_included(self):
        kwargs = game_to_match_kwargs(_game(), home_team_id=1, away_team_id=2)
        assert kwargs["external_id"] == "1001"

    def test_is_final_flag_carried(self):
        kwargs = game_to_match_kwargs(_game(is_final=True), home_team_id=1, away_team_id=2)
        assert kwargs["is_final"] is True

    def test_match_time_is_preserved(self):
        kwargs = game_to_match_kwargs(_game(), home_team_id=1, away_team_id=2)
        assert kwargs["match_time"] == _MATCH_TIME

    def test_returns_dict(self):
        assert isinstance(game_to_match_kwargs(_game(), 1, 2), dict)


# ---------------------------------------------------------------------------
# game_to_result_kwargs
# ---------------------------------------------------------------------------

class TestGameToResultKwargs:
    def test_returns_none_for_incomplete_game(self):
        assert game_to_result_kwargs(_game(is_complete=False)) is None

    def test_returns_result_dict_for_complete_game(self):
        g = _game(is_complete=True, result="away", home_score=70, away_score=95)
        kwargs = game_to_result_kwargs(g)
        assert kwargs is not None
        assert kwargs["result"] == "away"
        assert kwargs["home_score"] == 70
        assert kwargs["away_score"] == 95

    def test_does_not_include_identity_fields(self):
        g = _game(is_complete=True, result="home", home_score=100, away_score=80)
        kwargs = game_to_result_kwargs(g)
        assert "external_id" not in kwargs
        assert "season" not in kwargs


# ---------------------------------------------------------------------------
# game_to_schedule_kwargs
# ---------------------------------------------------------------------------

class TestGameToScheduleKwargs:
    def test_contains_only_schedule_fields(self):
        kwargs = game_to_schedule_kwargs(_game())
        assert set(kwargs.keys()) == {"match_time", "venue", "round_label"}

    def test_values_match_game(self):
        kwargs = game_to_schedule_kwargs(_game())
        assert kwargs["venue"] == "MCG"
        assert kwargs["round_label"] == "Round 5"
        assert kwargs["match_time"] == _MATCH_TIME


# ---------------------------------------------------------------------------
# _implied_probs (internal transformer utility)
# ---------------------------------------------------------------------------

class TestImpliedProbs:
    def test_basic_computation(self):
        home, away, overround = _implied_probs(2.0, 2.0)
        assert abs(home - 0.5) < 0.001
        assert abs(away - 0.5) < 0.001
        assert abs(overround - 1.0) < 0.001

    def test_probs_sum_to_one(self):
        home, away, _ = _implied_probs(1.75, 2.10)
        assert abs(home + away - 1.0) < 0.0001

    def test_overround_above_one_for_margin(self):
        _, _, overround = _implied_probs(1.80, 1.95)
        assert overround > 1.0

    def test_raises_on_odds_at_one(self):
        with pytest.raises(ValueError):
            _implied_probs(1.0, 2.0)

    def test_raises_on_odds_below_one(self):
        with pytest.raises(ValueError):
            _implied_probs(0.90, 2.0)

    def test_rounding_to_6_decimal_places(self):
        home, away, overround = _implied_probs(1.75, 2.10)
        # verify round() was applied (no more than 6 decimal places)
        assert len(str(home).split(".")[-1]) <= 6


# ---------------------------------------------------------------------------
# odds_event_to_snapshot_kwargs
# ---------------------------------------------------------------------------

class TestOddsEventToSnapshotKwargs:
    def test_contains_all_required_fields(self):
        kwargs = odds_event_to_snapshot_kwargs(_odds_event(), match_id=42, snapshot_time=_NOW)
        required = {
            "match_id", "bookmaker", "home_odds", "away_odds",
            "home_implied_prob", "away_implied_prob", "overround",
            "snapshot_time", "snapshot_type",
        }
        assert required.issubset(set(kwargs.keys()))

    def test_match_id_is_passed_through(self):
        kwargs = odds_event_to_snapshot_kwargs(_odds_event(), match_id=99, snapshot_time=_NOW)
        assert kwargs["match_id"] == 99

    def test_bookmaker_key_used_not_title(self):
        kwargs = odds_event_to_snapshot_kwargs(_odds_event(), match_id=1, snapshot_time=_NOW)
        assert kwargs["bookmaker"] == "tab"

    def test_implied_probs_sum_to_one(self):
        kwargs = odds_event_to_snapshot_kwargs(_odds_event(), match_id=1, snapshot_time=_NOW)
        total = kwargs["home_implied_prob"] + kwargs["away_implied_prob"]
        assert abs(total - 1.0) < 0.0001

    def test_default_snapshot_type_is_scheduled(self):
        kwargs = odds_event_to_snapshot_kwargs(_odds_event(), match_id=1, snapshot_time=_NOW)
        assert kwargs["snapshot_type"] == "scheduled"

    def test_custom_snapshot_type(self):
        kwargs = odds_event_to_snapshot_kwargs(
            _odds_event(), match_id=1, snapshot_time=_NOW, snapshot_type="closing"
        )
        assert kwargs["snapshot_type"] == "closing"

    def test_odds_preserved(self):
        kwargs = odds_event_to_snapshot_kwargs(_odds_event(), match_id=1, snapshot_time=_NOW)
        assert kwargs["home_odds"] == 1.75
        assert kwargs["away_odds"] == 2.10


# ---------------------------------------------------------------------------
# odds_event_to_update_kwargs
# ---------------------------------------------------------------------------

class TestOddsEventToUpdateKwargs:
    def test_does_not_include_identity_fields(self):
        kwargs = odds_event_to_update_kwargs(_odds_event(), snapshot_time=_NOW)
        # These are identity fields — must not be updated
        assert "match_id" not in kwargs
        assert "bookmaker" not in kwargs
        assert "snapshot_type" not in kwargs

    def test_includes_mutable_fields(self):
        kwargs = odds_event_to_update_kwargs(_odds_event(), snapshot_time=_NOW)
        assert "home_odds" in kwargs
        assert "away_odds" in kwargs
        assert "home_implied_prob" in kwargs
        assert "overround" in kwargs
        assert "snapshot_time" in kwargs

    def test_snapshot_time_is_passed_through(self):
        kwargs = odds_event_to_update_kwargs(_odds_event(), snapshot_time=_NOW)
        assert kwargs["snapshot_time"] == _NOW
