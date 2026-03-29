"""
tests/test_elo_extractor.py
----------------------------
Unit tests for features/extractors/elo.py.

No network calls, no database — pure function testing using minimal
Match-like objects.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from features.extractors.elo import (
    EloExtractor,
    _START_ELO,
    _expected_win,
    _outcome,
)


# ---------------------------------------------------------------------------
# Helpers — minimal Match-like objects
# ---------------------------------------------------------------------------

def _match(
    id: int,
    season: int,
    round_number: int,
    home_team_id: int,
    away_team_id: int,
    result: str | None = None,
    home_score: int | None = None,
    away_score: int | None = None,
    match_time: datetime | None = None,
) -> SimpleNamespace:
    """Create a minimal match-like namespace for testing extractors."""
    return SimpleNamespace(
        id=id,
        season=season,
        round_number=round_number,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        result=result,
        home_score=home_score,
        away_score=away_score,
        match_time=match_time or datetime(2025, 1, 1, tzinfo=timezone.utc),
        is_final=False,
        venue=None,
    )


_T1 = 1  # team IDs
_T2 = 2
_T3 = 3


# ---------------------------------------------------------------------------
# _expected_win helper
# ---------------------------------------------------------------------------

class TestExpectedWin:
    def test_equal_ratings_roughly_half(self):
        e = _expected_win(1500, 1500)
        # Home advantage means >0.5
        assert 0.5 < e < 0.7

    def test_much_stronger_home_team_near_one(self):
        e = _expected_win(2000, 1000)
        assert e > 0.99

    def test_much_weaker_home_team_near_zero(self):
        e = _expected_win(1000, 2000)
        assert e < 0.01


# ---------------------------------------------------------------------------
# _outcome helper
# ---------------------------------------------------------------------------

class TestOutcome:
    def test_home_win(self):
        assert _outcome("home") == 1.0

    def test_away_win(self):
        assert _outcome("away") == 0.0

    def test_draw(self):
        assert _outcome("draw") == 0.5

    def test_none_result(self):
        assert _outcome(None) is None

    def test_unknown_result(self):
        assert _outcome("unknown") is None


# ---------------------------------------------------------------------------
# EloExtractor.extract
# ---------------------------------------------------------------------------

class TestEloExtractor:
    def test_first_match_starts_at_default_elo(self):
        matches = [_match(1, 2025, 1, _T1, _T2, result=None)]
        result = EloExtractor().extract(matches)
        assert result[1]["home_elo_pre"] == pytest.approx(_START_ELO)
        assert result[1]["away_elo_pre"] == pytest.approx(_START_ELO)
        assert result[1]["elo_diff"] == pytest.approx(0.0)

    def test_all_matches_have_features(self):
        matches = [
            _match(1, 2025, 1, _T1, _T2, result="home"),
            _match(2, 2025, 2, _T2, _T3, result="away"),
            _match(3, 2025, 3, _T1, _T3, result=None),
        ]
        result = EloExtractor().extract(matches)
        assert set(result.keys()) == {1, 2, 3}

    def test_home_win_raises_home_elo(self):
        matches = [
            _match(1, 2025, 1, _T1, _T2, result="home"),
            _match(2, 2025, 2, _T1, _T2, result=None),
        ]
        result = EloExtractor().extract(matches)
        # After a home win, T1's pre-match ELO in match 2 should be > 1500
        assert result[2]["home_elo_pre"] > _START_ELO
        # T2's pre-match ELO in match 2 should be < 1500
        assert result[2]["away_elo_pre"] < _START_ELO

    def test_away_win_lowers_home_elo(self):
        matches = [
            _match(1, 2025, 1, _T1, _T2, result="away"),
            _match(2, 2025, 2, _T1, _T2, result=None),
        ]
        result = EloExtractor().extract(matches)
        assert result[2]["home_elo_pre"] < _START_ELO
        assert result[2]["away_elo_pre"] > _START_ELO

    def test_incomplete_match_does_not_update_elo(self):
        matches = [
            _match(1, 2025, 1, _T1, _T2, result=None),
            _match(2, 2025, 2, _T1, _T2, result=None),
        ]
        result = EloExtractor().extract(matches)
        # Both matches should show start ELO since no results were settled
        assert result[1]["home_elo_pre"] == pytest.approx(_START_ELO)
        assert result[2]["home_elo_pre"] == pytest.approx(_START_ELO)

    def test_season_regression_applied(self):
        matches = [
            # Season 2024: T1 wins many to build high ELO
            _match(1, 2024, 1, _T1, _T2, result="home"),
            _match(2, 2024, 2, _T1, _T2, result="home"),
            _match(3, 2024, 3, _T1, _T2, result="home"),
            # Season 2025: first match — ELO should be regressed toward 1500
            _match(4, 2025, 1, _T1, _T2, result=None),
        ]
        result = EloExtractor().extract(matches)
        # T1's pre-match ELO in 2025 should be between 1500 and its 2024 peak
        elo_2025 = result[4]["home_elo_pre"]
        assert elo_2025 > _START_ELO, "T1 should still be above average after regression"
        # It should also be lower than after 3 consecutive wins without regression
        elo_no_regression_3 = result[3]["home_elo_pre"]
        assert elo_2025 < elo_no_regression_3 + 50  # regression pulled it back

    def test_elo_diff_equals_home_minus_away(self):
        matches = [
            _match(1, 2025, 1, _T1, _T2, result="home"),
            _match(2, 2025, 2, _T1, _T2, result=None),
        ]
        result = EloExtractor().extract(matches)
        for mid in [1, 2]:
            row = result[mid]
            assert row["elo_diff"] == pytest.approx(
                row["home_elo_pre"] - row["away_elo_pre"], abs=0.01
            )

    def test_new_team_gets_start_elo(self):
        matches = [
            _match(1, 2025, 1, _T1, _T2, result="home"),
            _match(2, 2025, 2, _T1, _T3, result=None),  # T3 never seen before
        ]
        result = EloExtractor().extract(matches)
        assert result[2]["away_elo_pre"] == pytest.approx(_START_ELO)
