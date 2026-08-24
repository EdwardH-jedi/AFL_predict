"""
tests/test_calibration_aggregation.py
--------------------------------------
Guards the pooled-vs-seasonal calibration distinction (§1).

The defect: `aggregate_metrics` reported a single key `ece` computed as an
n_settled-weighted mean of per-season ECE, and documentation read it as a global
calibration figure. ECE bins predictions and compares each bin's mean prediction
to its empirical rate, so it is **not decomposable** — that weighted mean is a
different statistic from ECE over the pooled predictions. On the canonical
dataset the two disagree enough to reverse the calibration ranking.

Brier, log loss and accuracy *are* means of per-row quantities, so weighting
fold means by n_settled is exactly the pooled value. Those aggregations were
correct and must stay byte-identical.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from backtesting.calibration import expected_calibration_error
from backtesting.metrics import WindowMetrics, aggregate_metrics


def _window(fold: str, n_settled: int, ece: float, **kw) -> WindowMetrics:
    base: dict[str, object] = dict(
        model_name="m", fold_label=fold, n_matches=n_settled, n_settled=n_settled,
        brier_score=0.2, log_loss=0.6, accuracy=0.65, ece=ece,
        n_bets=0, n_no_bet=n_settled, hit_rate=math.nan, avg_edge=math.nan,
        total_staked=0.0, roi=math.nan,
    )
    base.update(kw)
    return WindowMetrics(**base)  # type: ignore[arg-type]  # heterogeneous test kwargs


# ---------------------------------------------------------------------------
# The two statistics must be distinguishable, and named
# ---------------------------------------------------------------------------

def test_no_bare_ece_key_in_aggregate():
    """A single key called 'ece' is what allowed the two to be conflated."""
    agg = aggregate_metrics([_window("2019", 100, 0.05)])
    assert "ece" not in agg, "aggregate must not expose an ambiguous bare 'ece'"
    assert "pooled_ece" in agg
    assert "season_weighted_ece" in agg


def test_pooled_ece_differs_from_season_weighted_on_a_constructed_fixture():
    """The canonical non-decomposability demonstration.

    Both seasons predict 0.7 — the same bin. Season A wins 90% of the time
    (under-confident, gap +0.2); season B wins 50% (over-confident, gap -0.2).
    Each season alone has ECE = 0.2, so the weighted mean is also 0.2.

    Pooled, all 400 predictions fall in one bin whose empirical rate is 0.7,
    exactly matching the prediction: pooled ECE is ~0. Same data, same metric
    definition, opposite conclusions — which is precisely why averaging
    per-season ECE cannot stand in for the pooled figure.
    """
    n = 200
    a = pd.DataFrame({"y_prob": np.full(n, 0.7), "y_true": [1] * 180 + [0] * 20})  # 90%
    b = pd.DataFrame({"y_prob": np.full(n, 0.7), "y_true": [1] * 100 + [0] * 100})  # 50%

    ece_a = expected_calibration_error(a.y_true.values, a.y_prob.values)
    ece_b = expected_calibration_error(b.y_true.values, b.y_prob.values)
    assert ece_a == pytest.approx(0.2, abs=1e-6)
    assert ece_b == pytest.approx(0.2, abs=1e-6)

    pooled = pd.concat([a, b], ignore_index=True)
    pooled_direct = expected_calibration_error(pooled.y_true.values, pooled.y_prob.values)
    assert pooled_direct == pytest.approx(0.0, abs=1e-6), "pooled bin is perfectly calibrated"

    agg = aggregate_metrics(
        [_window("A", n, ece_a), _window("B", n, ece_b)], pooled_predictions=pooled
    )
    assert agg["pooled_ece"] == pytest.approx(pooled_direct)
    assert agg["season_weighted_ece"] == pytest.approx(0.2, abs=1e-6)
    # The whole point: 0.0 vs 0.2 from identical data.
    assert abs(agg["pooled_ece"] - agg["season_weighted_ece"]) > 0.15


def test_pooled_ece_matches_direct_recomputation():
    rng = np.random.default_rng(7)
    n = 400
    probs = rng.uniform(0.05, 0.95, n)
    outcomes = (rng.uniform(size=n) < probs).astype(int)
    pooled = pd.DataFrame({"y_prob": probs, "y_true": outcomes})

    agg = aggregate_metrics(
        [_window("2019", 200, 0.04), _window("2020", 200, 0.06)],
        pooled_predictions=pooled,
    )
    assert agg["pooled_ece"] == pytest.approx(
        expected_calibration_error(outcomes, probs)
    )


def test_pooled_ece_is_none_without_predictions():
    """Better an explicit None than a wrong number silently standing in."""
    agg = aggregate_metrics([_window("2019", 100, 0.05)])
    assert agg["pooled_ece"] is None
    assert agg["season_weighted_ece"] == pytest.approx(0.05)


def test_unsettled_rows_are_excluded_from_pooled_ece():
    pooled = pd.DataFrame({
        "y_prob": [0.9, 0.9, 0.1, float("nan")],
        "y_true": [1.0, 1.0, 0.0, None],
    })
    agg = aggregate_metrics([_window("2019", 3, 0.02)], pooled_predictions=pooled)
    assert agg["pooled_ece"] == pytest.approx(
        expected_calibration_error([1, 1, 0], [0.9, 0.9, 0.1])
    )


# ---------------------------------------------------------------------------
# The decomposable metrics must not have changed
# ---------------------------------------------------------------------------

def test_decomposable_aggregations_are_unchanged():
    """Brier/log loss/accuracy stay n_settled-weighted, which is exact."""
    ws = [
        _window("2019", 100, 0.05, brier_score=0.20, log_loss=0.60, accuracy=0.70),
        _window("2020", 300, 0.09, brier_score=0.24, log_loss=0.68, accuracy=0.60),
    ]
    agg = aggregate_metrics(ws)
    assert agg["brier_score"] == pytest.approx((0.20 * 100 + 0.24 * 300) / 400)
    assert agg["log_loss"] == pytest.approx((0.60 * 100 + 0.68 * 300) / 400)
    assert agg["accuracy"] == pytest.approx((0.70 * 100 + 0.60 * 300) / 400)
    assert agg["season_weighted_ece"] == pytest.approx((0.05 * 100 + 0.09 * 300) / 400)


def test_weighted_mean_equals_pooled_for_brier():
    """Proof that _wavg is exact for a per-row mean, unlike for ECE."""
    rng = np.random.default_rng(3)
    pa = rng.uniform(size=120)
    ya = rng.integers(0, 2, 120)
    pb = rng.uniform(size=280)
    yb = rng.integers(0, 2, 280)
    ba = float(((pa - ya) ** 2).mean())
    bb = float(((pb - yb) ** 2).mean())
    pooled_brier = float(((np.concatenate([pa, pb]) - np.concatenate([ya, yb])) ** 2).mean())
    weighted = (ba * 120 + bb * 280) / 400
    assert weighted == pytest.approx(pooled_brier)


# ---------------------------------------------------------------------------
# Decision metrics: pooled vs macro (§13)
# ---------------------------------------------------------------------------

def test_pooled_and_macro_hit_rate_are_both_reported_and_differ():
    ws = [
        _window("2019", 100, 0.05, n_bets=10, n_bets_settled=10, n_bets_won=9,
                hit_rate=0.9, avg_edge=0.10, edge_sum=1.0),
        _window("2020", 100, 0.05, n_bets=90, n_bets_settled=90, n_bets_won=9,
                hit_rate=0.1, avg_edge=0.20, edge_sum=18.0),
    ]
    agg = aggregate_metrics(ws)
    assert agg["pooled_hit_rate"] == pytest.approx(18 / 100)
    assert agg["macro_season_hit_rate"] == pytest.approx(0.5)
    assert agg["n_bets_won_total"] == 18
    assert agg["n_bets_settled_total"] == 100
    assert agg["pooled_avg_edge"] == pytest.approx(19.0 / 100)
