"""
tests/test_simulation.py
-------------------------
Unit tests for backtesting/simulation.py.

No network, no database.
"""

from __future__ import annotations

import pandas as pd
import pytest

from backtesting.simulation import _kelly_fraction, settle_bets, simulate_recommendations

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _preds(*rows) -> pd.DataFrame:
    """Build predictions DataFrame from (match_id, home_prob, away_prob) tuples."""
    return pd.DataFrame(rows, columns=["match_id", "home_win_prob", "away_win_prob"])


def _features(*rows) -> pd.DataFrame:
    """Build features DataFrame from (match_id, bm_h_imp, bm_a_imp, bm_h_odds, bm_a_odds) tuples."""
    return pd.DataFrame(rows, columns=[
        "match_id", "bm_home_implied_prob", "bm_away_implied_prob",
        "bm_home_odds", "bm_away_odds",
    ])


# ---------------------------------------------------------------------------
# _kelly_fraction
# ---------------------------------------------------------------------------

class TestKellyFraction:
    def test_positive_edge_positive_kelly(self):
        # prob=0.6, odds=2.0 → b=1, f=(1*0.6 - 0.4)/1 = 0.2
        assert _kelly_fraction(0.6, 2.0) == pytest.approx(0.2)

    def test_negative_edge_returns_zero(self):
        # prob=0.4, odds=2.0 → f=(1*0.4 - 0.6)/1 = -0.2 → clamp to 0
        assert _kelly_fraction(0.4, 2.0) == pytest.approx(0.0)

    def test_odds_at_one_returns_zero(self):
        assert _kelly_fraction(0.9, 1.0) == pytest.approx(0.0)

    def test_high_prob_high_kelly(self):
        # prob=0.9, odds=1.5 → b=0.5, f=(0.5*0.9-0.1)/0.5 = 0.7
        assert _kelly_fraction(0.9, 1.5) == pytest.approx(0.7)


# ---------------------------------------------------------------------------
# simulate_recommendations
# ---------------------------------------------------------------------------

class TestSimulateRecommendations:
    def test_no_edge_returns_empty(self):
        preds = _preds((1, 0.50, 0.50))
        feats = _features((1, 0.52, 0.48, 1.90, 2.10))
        bets = simulate_recommendations(preds, feats, edge_threshold=0.05)
        assert len(bets) == 0

    def test_home_edge_above_threshold_recommends_bet(self):
        # home_prob=0.60, bm_implied=0.50 → edge=0.10 > 0.03 → recommend
        preds = _preds((1, 0.60, 0.40))
        feats = _features((1, 0.50, 0.50, 2.0, 2.0))
        bets = simulate_recommendations(preds, feats, edge_threshold=0.03)
        assert len(bets) == 1
        assert bets.iloc[0]["side"] == "home"
        assert bets.iloc[0]["edge"] == pytest.approx(0.10)

    def test_away_edge_recommends_away_side(self):
        # away_prob=0.65, bm_implied_away=0.50 → edge=0.15
        preds = _preds((1, 0.35, 0.65))
        feats = _features((1, 0.50, 0.50, 2.0, 2.0))
        bets = simulate_recommendations(preds, feats, edge_threshold=0.03)
        assert len(bets) == 1
        assert bets.iloc[0]["side"] == "away"

    def test_stake_capped_at_max_kelly(self):
        # Kelly would be large but should be capped
        preds = _preds((1, 0.95, 0.05))
        feats = _features((1, 0.40, 0.60, 2.5, 1.5))
        bets = simulate_recommendations(
            preds, feats, edge_threshold=0.03, max_kelly_fraction=0.05
        )
        assert len(bets) == 1
        assert bets.iloc[0]["stake_fraction"] == pytest.approx(0.05)

    def test_missing_bm_odds_skips_match(self):
        preds = _preds((1, 0.70, 0.30))
        feats = _features((1, None, None, None, None))
        bets = simulate_recommendations(preds, feats, edge_threshold=0.03)
        assert len(bets) == 0

    def test_multiple_matches_processed(self):
        preds = _preds(
            (1, 0.60, 0.40),   # edge 0.10 → bet
            (2, 0.51, 0.49),   # edge 0.01 → no bet
            (3, 0.65, 0.35),   # edge 0.15 → bet
        )
        feats = _features(
            (1, 0.50, 0.50, 2.0, 2.0),
            (2, 0.50, 0.50, 2.0, 2.0),
            (3, 0.50, 0.50, 2.0, 2.0),
        )
        bets = simulate_recommendations(preds, feats, edge_threshold=0.05)
        assert len(bets) == 2
        assert set(bets["match_id"]) == {1, 3}

    def test_one_bet_per_match(self):
        # Both sides have positive edge — should still produce only one bet
        preds = _preds((1, 0.60, 0.55))  # won't sum to 1 but that's OK for this test
        feats = _features((1, 0.50, 0.40, 2.0, 2.5))
        bets = simulate_recommendations(preds, feats, edge_threshold=0.03)
        assert len(bets) <= 1

    def test_invalid_edge_threshold_raises(self):
        with pytest.raises(ValueError):
            simulate_recommendations(_preds(), _features(), edge_threshold=0.0)

    def test_missing_predictions_column_raises(self):
        bad_preds = pd.DataFrame({"match_id": [1], "home_win_prob": [0.6]})
        feats = _features((1, 0.50, 0.50, 2.0, 2.0))
        with pytest.raises(ValueError):
            simulate_recommendations(bad_preds, feats)


# ---------------------------------------------------------------------------
# settle_bets
# ---------------------------------------------------------------------------

class TestSettleBets:
    def _make_bets(self) -> pd.DataFrame:
        return pd.DataFrame({
            "match_id": [1, 2, 3],
            "side": ["home", "away", "home"],
            "bm_odds": [1.80, 2.20, 1.90],
            "stake_fraction": [0.04, 0.03, 0.05],
        })

    def test_home_bet_wins(self):
        bets = self._make_bets()
        result_map = {1: 1, 2: 0, 3: 0}  # match 1: home win, match 2: away win, match 3: away win
        settled = settle_bets(bets, pd.Series(), match_id_to_result=result_map)
        # match 1: home bet, home wins. match 2: away bet, away wins.
        # match 3: home bet, away wins. tolist() normalises numpy bools.
        won_by_match = dict(zip(settled["match_id"].tolist(), settled["won"].tolist()))
        assert won_by_match == {1: True, 2: True, 3: False}

    def test_profit_positive_on_win(self):
        bets = self._make_bets().iloc[:1]  # only match 1, home bet
        settled = settle_bets(bets, pd.Series(), match_id_to_result={1: 1})
        profit = settled["profit"].values[0]
        expected = 0.04 * (1.80 - 1.0)
        assert profit == pytest.approx(expected)

    def test_profit_negative_on_loss(self):
        bets = self._make_bets().iloc[:1]  # match 1, home bet
        settled = settle_bets(bets, pd.Series(), match_id_to_result={1: 0})  # home loses
        profit = settled["profit"].values[0]
        assert profit == pytest.approx(-0.04)

    def test_unsettled_match_returns_none(self):
        bets = self._make_bets().iloc[:1]
        settled = settle_bets(bets, pd.Series(), match_id_to_result={1: None})
        assert settled["won"].values[0] is None
        assert settled["profit"].values[0] is None

    def test_settle_from_series(self):
        bets = self._make_bets().iloc[:1]
        actuals = pd.Series({1: 1})
        settled = settle_bets(bets, actuals)
        assert settled["won"].tolist() == [True]
