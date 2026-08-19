"""
tests/test_metrics.py
----------------------
Unit tests for backtesting/metrics.py and backtesting/calibration.py.

No network, no database.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from backtesting.calibration import (
    calibration_bins,
    expected_calibration_error,
    format_calibration_report,
)
from backtesting.metrics import WindowMetrics, aggregate_metrics, compute_metrics

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _preds(match_ids, home_probs) -> pd.DataFrame:
    return pd.DataFrame({
        "match_id": match_ids,
        "home_win_prob": home_probs,
        "away_win_prob": [1 - p for p in home_probs],
    })


def _actuals(match_ids, outcomes) -> pd.Series:
    return pd.Series(outcomes, index=match_ids)


# ---------------------------------------------------------------------------
# calibration_bins
# ---------------------------------------------------------------------------

class TestCalibrationBins:
    def test_perfect_calibration_produces_zero_gap(self):
        # Predicted 0.6 → actual 60% win rate
        y_true = [1] * 6 + [0] * 4
        y_prob = [0.6] * 10
        bins = calibration_bins(y_true, y_prob)
        assert len(bins) == 1
        b = bins[0]
        assert abs(b.actual_fraction - 0.6) < 0.01
        assert abs(b.mean_predicted - 0.6) < 0.01
        assert abs(b.gap) < 0.01

    def test_empty_bins_excluded(self):
        # All predictions in [0.5, 0.6) bin — other bins empty
        y_true = [1, 0, 1, 1, 0]
        y_prob = [0.55, 0.52, 0.58, 0.51, 0.57]
        bins = calibration_bins(y_true, y_prob, n_bins=10)
        assert len(bins) == 1  # only one bin has data

    def test_count_sums_to_total(self):
        y_true = [1, 0, 1, 0, 1, 0, 1, 0, 1, 0]
        y_prob = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95]
        bins = calibration_bins(y_true, y_prob, n_bins=10)
        assert sum(b.count for b in bins) == 10

    def test_nan_values_excluded(self):
        y_true = [1, 0, float("nan"), 1]
        y_prob = [0.7, 0.3, float("nan"), 0.8]
        bins = calibration_bins(y_true, y_prob)
        assert sum(b.count for b in bins) == 3  # NaN row excluded

    def test_bins_ordered_by_probability(self):
        y_true = [1] * 5 + [0] * 5
        y_prob = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95]
        bins = calibration_bins(y_true, y_prob)
        lows = [b.bin_low for b in bins]
        assert lows == sorted(lows)


# ---------------------------------------------------------------------------
# expected_calibration_error
# ---------------------------------------------------------------------------

class TestECE:
    def test_perfect_calibration_zero_ece(self):
        # Assign 60% probability and 60% win rate
        n = 100
        y_true = [1] * 60 + [0] * 40
        y_prob = [0.6] * n
        ece = expected_calibration_error(y_true, y_prob)
        assert ece < 0.01

    def test_worst_case_high_ece(self):
        # Assign 90% probability but only 10% win rate
        n = 100
        y_true = [1] * 10 + [0] * 90
        y_prob = [0.9] * n
        ece = expected_calibration_error(y_true, y_prob)
        assert ece > 0.50

    def test_empty_input_returns_nan(self):
        ece = expected_calibration_error([], [])
        assert math.isnan(ece)

    def test_all_nan_returns_nan(self):
        y_true = [float("nan"), float("nan")]
        y_prob = [float("nan"), float("nan")]
        ece = expected_calibration_error(y_true, y_prob)
        assert math.isnan(ece)

    def test_returns_value_in_zero_one(self):
        rng = np.random.default_rng(42)
        y_true = rng.integers(0, 2, size=200)
        y_prob = rng.uniform(0.3, 0.7, size=200)
        ece = expected_calibration_error(y_true, y_prob)
        assert 0.0 <= ece <= 1.0


# ---------------------------------------------------------------------------
# format_calibration_report
# ---------------------------------------------------------------------------

class TestFormatCalibrationReport:
    def test_output_is_string(self):
        bins = calibration_bins([1, 0, 1], [0.7, 0.3, 0.8])
        report = format_calibration_report(bins, model_name="TestModel")
        assert isinstance(report, str)
        assert "TestModel" in report
        assert "Mean Pred" in report

    def test_empty_bins_produces_report(self):
        report = format_calibration_report([], model_name="Empty")
        assert "Empty" in report


# ---------------------------------------------------------------------------
# compute_metrics
# ---------------------------------------------------------------------------

class TestComputeMetrics:
    def _make_bets(self, n_bets, win_rate, edge=0.04, stake=0.03, odds=2.0) -> pd.DataFrame:
        n_wins = int(n_bets * win_rate)
        n_losses = n_bets - n_wins
        won_col = [True] * n_wins + [False] * n_losses
        profit_col = [stake * (odds - 1)] * n_wins + [-stake] * n_losses
        return pd.DataFrame({
            "match_id": list(range(n_bets)),
            "side": ["home"] * n_bets,
            "model_prob": [0.55] * n_bets,
            "bm_implied_prob": [0.51] * n_bets,
            "bm_odds": [odds] * n_bets,
            "edge": [edge] * n_bets,
            "kelly_fraction": [stake] * n_bets,
            "stake_fraction": [stake] * n_bets,
            "won": won_col,
            "profit": profit_col,
        })

    def test_brier_score_correct(self):
        match_ids = list(range(10))
        y_prob = [0.7] * 10
        y_true = [1] * 10
        preds = _preds(match_ids, y_prob)
        actuals = _actuals(range(10), y_true)
        wm = compute_metrics("test", "2023", preds, actuals)
        # Brier = mean((0.7 - 1)^2 = 0.09)
        assert abs(wm.brier_score - 0.09) < 0.001

    def test_accuracy_all_correct(self):
        match_ids = list(range(5))
        preds = _preds(match_ids, [0.9, 0.8, 0.7, 0.75, 0.85])
        actuals = _actuals(range(5), [1, 1, 1, 1, 1])
        wm = compute_metrics("test", "2023", preds, actuals)
        assert wm.accuracy == pytest.approx(1.0)

    def test_unsettled_matches_excluded_from_prob_metrics(self):
        match_ids = list(range(5))
        preds = _preds(match_ids, [0.7, 0.6, 0.5, 0.8, 0.65])
        # Only first 3 are settled
        actuals = _actuals(range(5), [1, 1, 0, None, None])
        wm = compute_metrics("test", "2023", preds, actuals)
        assert wm.n_settled == 3
        assert not math.isnan(wm.brier_score)

    def test_no_settled_matches_returns_nan_metrics(self):
        match_ids = list(range(3))
        preds = _preds(match_ids, [0.5, 0.5, 0.5])
        actuals = _actuals(range(3), [None, None, None])
        wm = compute_metrics("test", "2023", preds, actuals)
        assert wm.n_settled == 0
        assert math.isnan(wm.brier_score)

    def test_roi_computed_correctly(self):
        # 5 bets at 50% win rate, stake=0.04, odds=2.0 → profit = 0 each on average
        bets = self._make_bets(10, win_rate=0.5, stake=0.04, odds=2.0)
        total_profit = bets["profit"].sum()
        expected_roi = total_profit / (10 * 0.04)

        preds = _preds(list(range(10)), [0.55] * 10)
        actuals = _actuals(range(10), [1] * 5 + [0] * 5)
        wm = compute_metrics("test", "2023", preds, actuals, simulated_bets=bets)
        assert wm.roi == pytest.approx(expected_roi, abs=0.001)

    def test_hit_rate_computed(self):
        bets = self._make_bets(10, win_rate=0.6)
        preds = _preds(list(range(10)), [0.6] * 10)
        actuals = _actuals(range(10), [1] * 6 + [0] * 4)
        wm = compute_metrics("test", "2023", preds, actuals, simulated_bets=bets)
        assert wm.hit_rate == pytest.approx(0.6, abs=0.01)

    def test_n_no_bet_counts_settled_not_bet(self):
        # 4 settled matches but only 2 bets
        preds = _preds(list(range(4)), [0.6, 0.65, 0.5, 0.55])
        actuals = _actuals(range(4), [1, 0, 1, 0])
        bets = self._make_bets(2, win_rate=0.5)
        wm = compute_metrics("test", "2023", preds, actuals, simulated_bets=bets)
        assert wm.n_bets == 2
        assert wm.n_no_bet == 2


# ---------------------------------------------------------------------------
# aggregate_metrics
# ---------------------------------------------------------------------------

class TestAggregateMetrics:
    def _make_window(self, brier, n_settled, n_bets=0) -> WindowMetrics:
        import math
        return WindowMetrics(
            model_name="test", fold_label="2023",
            n_matches=n_settled, n_settled=n_settled,
            brier_score=brier, log_loss=0.5, accuracy=0.6, ece=0.05,
            n_bets=n_bets, n_no_bet=n_settled - n_bets,
            hit_rate=math.nan, avg_edge=math.nan,
            total_staked=0.0, roi=math.nan,
        )

    def test_empty_list_returns_empty_dict(self):
        assert aggregate_metrics([]) == {}

    def test_weighted_average_by_n_settled(self):
        # Two folds: brier=0.2 (n=100) and brier=0.4 (n=100) → avg=0.3
        w1 = self._make_window(brier=0.2, n_settled=100)
        w2 = self._make_window(brier=0.4, n_settled=100)
        agg = aggregate_metrics([w1, w2])
        assert agg["brier_score"] == pytest.approx(0.3, abs=0.001)

    def test_n_bets_summed(self):
        w1 = self._make_window(0.25, 100, n_bets=10)
        w2 = self._make_window(0.25, 100, n_bets=15)
        agg = aggregate_metrics([w1, w2])
        assert agg["n_bets_total"] == 25

    def test_n_folds_counted(self):
        windows = [self._make_window(0.25, 100) for _ in range(3)]
        agg = aggregate_metrics(windows)
        assert agg["n_folds"] == 3
