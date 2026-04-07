"""
backtesting/bootstrap.py
-------------------------
Bootstrap confidence intervals for backtest metrics.

AFL backtest samples are small (≈100-200 bets per season).  A raw backtest
ROI of +4% can easily be within noise — bootstrap CIs make this honest.

Usage:
    records = [{"profit": 0.05, "stake": 0.04, "won": True, "brier_contrib": 0.18}, ...]
    ci = bootstrap_metrics(records, n_iter=1000)
    print(ci)
    # BootstrapCI(roi_mean=0.042, roi_ci=(−0.008, 0.094), ...)

Design:
  - Resamples the bet list (with replacement) N times.
  - Computes ROI, hit_rate, and Sharpe ratio on each resample.
  - Reports 2.5th / 97.5th percentiles as the 95% CI.
  - Brier CI resamples match-level predictions (not bet-level).

Public API:
    bootstrap_metrics(bet_records, n_iter=1000, seed=42) → BootstrapCI
    bootstrap_brier(y_true, y_prob, n_iter=1000, seed=42) → tuple[float, float]
    format_ci(ci) → str    pretty ASCII summary
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Sequence

import numpy as np


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class BootstrapCI:
    """95% confidence intervals for key backtest metrics."""

    n_bets: int
    n_iter: int

    # ROI
    roi_mean: float | None
    roi_ci_low: float | None       # 2.5th percentile
    roi_ci_high: float | None      # 97.5th percentile

    # Hit rate
    hit_rate_mean: float | None
    hit_rate_ci_low: float | None
    hit_rate_ci_high: float | None

    # Sharpe (mean per-bet return / std)
    sharpe_mean: float | None
    sharpe_ci_low: float | None
    sharpe_ci_high: float | None

    def is_significant(self, metric: str = "roi") -> bool:
        """
        True if the CI for `metric` is entirely above zero.
        metric: 'roi' | 'hit_rate' | 'sharpe'
        """
        low_map = {"roi": self.roi_ci_low, "hit_rate": self.hit_rate_ci_low, "sharpe": self.sharpe_ci_low}
        low = low_map.get(metric)
        return low is not None and low > 0

    def to_dict(self) -> dict:
        return {
            "n_bets": self.n_bets,
            "n_iter": self.n_iter,
            "roi": {
                "mean": _fmt(self.roi_mean),
                "ci_low": _fmt(self.roi_ci_low),
                "ci_high": _fmt(self.roi_ci_high),
                "significant": self.is_significant("roi"),
            },
            "hit_rate": {
                "mean": _fmt(self.hit_rate_mean),
                "ci_low": _fmt(self.hit_rate_ci_low),
                "ci_high": _fmt(self.hit_rate_ci_high),
                "significant": self.is_significant("hit_rate"),
            },
            "sharpe": {
                "mean": _fmt(self.sharpe_mean),
                "ci_low": _fmt(self.sharpe_ci_low),
                "ci_high": _fmt(self.sharpe_ci_high),
                "significant": self.is_significant("sharpe"),
            },
        }


# ---------------------------------------------------------------------------
# Main bootstrap function
# ---------------------------------------------------------------------------

def bootstrap_metrics(
    bet_records: Sequence[dict],
    n_iter: int = 1000,
    seed: int = 42,
) -> BootstrapCI:
    """
    Compute 95% bootstrap confidence intervals for ROI, hit_rate, and Sharpe.

    Args:
        bet_records: List of dicts, each representing one settled bet.
                     Required keys: 'profit' (float), 'stake_fraction' (float),
                                    'won' (bool).
                     profit = stake * (odds-1) if won, else -stake.
        n_iter:      Number of bootstrap resamples (default 1000).
        seed:        Random seed for reproducibility.

    Returns:
        BootstrapCI with mean and 95% CI for each metric.
        Returns all-None CI if fewer than 5 bets are provided.
    """
    records = [r for r in bet_records if r.get("profit") is not None]
    n = len(records)

    if n < 5:
        return BootstrapCI(
            n_bets=n, n_iter=n_iter,
            roi_mean=None, roi_ci_low=None, roi_ci_high=None,
            hit_rate_mean=None, hit_rate_ci_low=None, hit_rate_ci_high=None,
            sharpe_mean=None, sharpe_ci_low=None, sharpe_ci_high=None,
        )

    rng = random.Random(seed)

    roi_samples: list[float] = []
    hit_samples: list[float] = []
    sharpe_samples: list[float] = []

    for _ in range(n_iter):
        sample = [records[rng.randint(0, n - 1)] for _ in range(n)]

        profits = [r["profit"] for r in sample]
        stakes = [r["stake_fraction"] for r in sample]
        wins = [1 if r.get("won") else 0 for r in sample]

        total_staked = sum(stakes)
        roi = sum(profits) / total_staked if total_staked > 0 else math.nan
        hit = sum(wins) / n

        returns_on_stake = [
            p / s if s > 0 else 0.0
            for p, s in zip(profits, stakes)
        ]
        std_r = float(np.std(returns_on_stake))
        sharpe = float(np.mean(returns_on_stake)) / std_r if std_r > 1e-9 else math.nan

        if not math.isnan(roi):
            roi_samples.append(roi)
        hit_samples.append(hit)
        if not math.isnan(sharpe):
            sharpe_samples.append(sharpe)

    def _ci(samples: list[float]) -> tuple[float | None, float | None, float | None]:
        if not samples:
            return None, None, None
        arr = sorted(samples)
        n_s = len(arr)
        low = arr[int(n_s * 0.025)]
        high = arr[int(n_s * 0.975)]
        mean = sum(arr) / n_s
        return round(mean, 6), round(low, 6), round(high, 6)

    roi_mean, roi_low, roi_high = _ci(roi_samples)
    hit_mean, hit_low, hit_high = _ci(hit_samples)
    sharpe_mean, sharpe_low, sharpe_high = _ci(sharpe_samples)

    return BootstrapCI(
        n_bets=n,
        n_iter=n_iter,
        roi_mean=roi_mean,
        roi_ci_low=roi_low,
        roi_ci_high=roi_high,
        hit_rate_mean=hit_mean,
        hit_rate_ci_low=hit_low,
        hit_rate_ci_high=hit_high,
        sharpe_mean=sharpe_mean,
        sharpe_ci_low=sharpe_low,
        sharpe_ci_high=sharpe_high,
    )


def bootstrap_brier(
    y_true: Sequence[int],
    y_prob: Sequence[float],
    n_iter: int = 1000,
    seed: int = 42,
) -> tuple[float, float]:
    """
    95% bootstrap CI for Brier score.

    Args:
        y_true: Binary outcomes (1=home win, 0=away win).
        y_prob: Predicted home-win probability.
        n_iter: Bootstrap iterations.
        seed:   Random seed.

    Returns:
        (ci_low, ci_high) at 95% confidence.
    """
    pairs = list(zip(y_true, y_prob))
    n = len(pairs)
    if n < 5:
        return (math.nan, math.nan)

    rng = random.Random(seed)
    brier_samples: list[float] = []

    for _ in range(n_iter):
        sample = [pairs[rng.randint(0, n - 1)] for _ in range(n)]
        yt = [p[0] for p in sample]
        yp = [p[1] for p in sample]
        brier = sum((p - t) ** 2 for t, p in zip(yt, yp)) / n
        brier_samples.append(brier)

    brier_samples.sort()
    n_s = len(brier_samples)
    return (
        round(brier_samples[int(n_s * 0.025)], 6),
        round(brier_samples[int(n_s * 0.975)], 6),
    )


# ---------------------------------------------------------------------------
# Formatting helper
# ---------------------------------------------------------------------------

def format_ci(ci: BootstrapCI) -> str:
    """
    Return a compact ASCII summary of the bootstrap CI.

    Example output:
        Bootstrap CI (n=187 bets, 1000 iterations)
          ROI    :  +4.2%  [95% CI: -0.8% .. +9.4%]  ✗ not significant
          HitRate:  54.0%  [95% CI: 47.3% .. 60.9%]  ✓ significant
          Sharpe :  +0.38  [95% CI: -0.05 .. +0.82]  ✗ not significant
    """
    def _pct(v: float | None, decimals: int = 1) -> str:
        if v is None:
            return "N/A"
        return f"{v * 100:+.{decimals}f}%"

    def _val(v: float | None) -> str:
        if v is None:
            return "N/A"
        return f"{v:+.2f}"

    sig = lambda metric: "[SIG]" if ci.is_significant(metric) else "[not sig]"  # noqa: E731

    lines = [
        f"Bootstrap CI (n={ci.n_bets} bets, {ci.n_iter} iterations)",
        f"  ROI    : {_pct(ci.roi_mean)}  [95% CI: {_pct(ci.roi_ci_low)} .. {_pct(ci.roi_ci_high)}]  {sig('roi')}",
        f"  HitRate: {_pct(ci.hit_rate_mean)}  [95% CI: {_pct(ci.hit_rate_ci_low)} .. {_pct(ci.hit_rate_ci_high)}]  {sig('hit_rate')}",
        f"  Sharpe : {_val(ci.sharpe_mean)}  [95% CI: {_val(ci.sharpe_ci_low)} .. {_val(ci.sharpe_ci_high)}]  {sig('sharpe')}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt(v: float | None) -> float | None:
    if v is None or math.isnan(v):
        return None
    return v
