"""
tests/test_form_extractor.py
-----------------------------
Unit tests for features/extractors/form.py.

No network calls, no database — pure function testing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from features.extractors.form import _DEFAULT_WINDOW, FormExtractor

# ---------------------------------------------------------------------------
# Helpers
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
) -> SimpleNamespace:
    return SimpleNamespace(
        id=id,
        season=season,
        round_number=round_number,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        result=result,
        home_score=home_score,
        away_score=away_score,
        match_time=datetime(2025, 1, round_number, tzinfo=UTC),
        is_final=False,
        venue=None,
    )


_T1 = 1
_T2 = 2
_T3 = 3


# ---------------------------------------------------------------------------
# FormExtractor tests
# ---------------------------------------------------------------------------

class TestFormExtractor:
    def test_no_prior_games_returns_all_none(self):
        matches = [_match(1, 2025, 1, _T1, _T2, result=None)]
        result = FormExtractor().extract(matches)
        row = result[1]
        assert row["home_win_rate_l10"] is None
        assert row["home_avg_pts_for_l10"] is None
        assert row["away_win_rate_l10"] is None

    def test_all_matches_are_keyed(self):
        matches = [
            _match(1, 2025, 1, _T1, _T2, result="home", home_score=100, away_score=80),
            _match(2, 2025, 2, _T1, _T3, result=None),
        ]
        result = FormExtractor().extract(matches)
        assert 1 in result
        assert 2 in result

    def test_win_rate_after_one_win(self):
        matches = [
            _match(1, 2025, 1, _T1, _T2, result="home", home_score=100, away_score=80),
            _match(2, 2025, 2, _T1, _T2, result=None),
        ]
        result = FormExtractor().extract(matches)
        # T1 won match 1 as home — should show 100% win rate in match 2
        assert result[2]["home_win_rate_l10"] == pytest.approx(1.0)

    def test_win_rate_after_one_loss(self):
        matches = [
            _match(1, 2025, 1, _T1, _T2, result="away", home_score=80, away_score=100),
            _match(2, 2025, 2, _T1, _T2, result=None),
        ]
        result = FormExtractor().extract(matches)
        assert result[2]["home_win_rate_l10"] == pytest.approx(0.0)

    def test_avg_pts_for_computed_correctly(self):
        matches = [
            _match(1, 2025, 1, _T1, _T2, result="home", home_score=100, away_score=80),
            _match(2, 2025, 2, _T1, _T2, result="home", home_score=120, away_score=60),
            _match(3, 2025, 3, _T1, _T2, result=None),
        ]
        result = FormExtractor().extract(matches)
        # T1 scored 100 + 120 in 2 games → avg 110
        assert result[3]["home_avg_pts_for_l10"] == pytest.approx(110.0)

    def test_away_team_form_tracked_separately(self):
        matches = [
            # T2 wins as away team
            _match(1, 2025, 1, _T1, _T2, result="away", home_score=80, away_score=100),
            # T2 plays as home team — prior win should count
            _match(2, 2025, 2, _T2, _T3, result=None),
        ]
        result = FormExtractor().extract(matches)
        # T2 as home should see its 1 prior win
        assert result[2]["home_win_rate_l10"] == pytest.approx(1.0)

    def test_window_limits_lookback(self):
        # Use window=3, give T1 5 games: 3 wins then 2 losses
        matches = [
            _match(1, 2025, 1, _T1, _T2, result="home", home_score=100, away_score=80),
            _match(2, 2025, 2, _T1, _T2, result="home", home_score=100, away_score=80),
            _match(3, 2025, 3, _T1, _T2, result="home", home_score=100, away_score=80),
            _match(4, 2025, 4, _T1, _T2, result="away", home_score=80, away_score=100),
            _match(5, 2025, 5, _T1, _T2, result="away", home_score=80, away_score=100),
            # Match 6: form window of 3 should see only games 3,4,5
            _match(6, 2025, 6, _T1, _T2, result=None),
        ]
        result = FormExtractor(window=3).extract(matches)
        # Window = [game3 win, game4 loss, game5 loss] → win_rate = 1/3
        assert result[6]["home_win_rate_l3"] == pytest.approx(1 / 3, abs=0.001)

    def test_incomplete_games_excluded_from_form(self):
        matches = [
            _match(1, 2025, 1, _T1, _T2, result=None),  # no result
            _match(2, 2025, 2, _T1, _T2, result=None),  # no result
            _match(3, 2025, 3, _T1, _T2, result=None),
        ]
        result = FormExtractor().extract(matches)
        # No completed games → all form features None for match 3
        assert result[3]["home_win_rate_l10"] is None

    def test_feature_keys_present(self):
        matches = [_match(1, 2025, 1, _T1, _T2)]
        result = FormExtractor().extract(matches)
        row = result[1]
        s = f"l{_DEFAULT_WINDOW}"
        for key in [
            f"home_win_rate_{s}", f"home_avg_pts_for_{s}", f"home_avg_pts_against_{s}",
            f"away_win_rate_{s}", f"away_avg_pts_for_{s}", f"away_avg_pts_against_{s}",
        ]:
            assert key in row, f"Missing feature key: {key}"
