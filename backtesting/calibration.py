"""
backtesting/calibration.py
---------------------------
Calibration analysis utilities.

A well-calibrated model's predicted probability p should equal the empirical
win rate across all matches where the model assigned probability p. For example,
in 100 matches where the model says "60% home win", roughly 60 should be home wins.

Tools provided:
  - calibration_bins: bucket predictions into N equal-width probability bins
  - expected_calibration_error: scalar summary of miscalibration
  - format_calibration_report: human-readable table for logging

These are pure functions — no I/O, no model dependencies.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class CalibrationBin:
    """Statistics for one probability bin."""
    bin_low: float          # lower bound (inclusive)
    bin_high: float         # upper bound (exclusive for all but last)
    mean_predicted: float   # average predicted probability within this bin
    actual_fraction: float  # empirical win rate within this bin
    count: int              # number of samples in this bin

    @property
    def gap(self) -> float:
        """Signed gap: actual - predicted. Positive = underpredicting."""
        return self.actual_fraction - self.mean_predicted

    @property
    def abs_gap(self) -> float:
        return abs(self.gap)


def calibration_bins(
    y_true: pd.Series | np.ndarray,
    y_prob: pd.Series | np.ndarray,
    n_bins: int = 10,
) -> list[CalibrationBin]:
    """
    Bucket predictions into equal-width probability bins.

    Empty bins (no predictions in range) are excluded from the result.

    Args:
        y_true: Binary outcomes (1 = positive, 0 = negative).
        y_prob: Predicted probabilities in [0, 1].
        n_bins: Number of equal-width bins. Default 10 gives [0,0.1),[0.1,0.2),...

    Returns:
        List of CalibrationBin objects (only non-empty bins).
    """
    y_true = np.asarray(y_true, dtype=float)
    y_prob = np.asarray(y_prob, dtype=float)

    # Drop rows with NaN
    mask = ~(np.isnan(y_true) | np.isnan(y_prob))
    y_true = y_true[mask]
    y_prob = y_prob[mask]

    bins_result: list[CalibrationBin] = []
    edges = np.linspace(0.0, 1.0, n_bins + 1)

    for i in range(n_bins):
        lo = edges[i]
        hi = edges[i + 1]
        # Last bin is inclusive on both ends
        if i < n_bins - 1:
            in_bin = (y_prob >= lo) & (y_prob < hi)
        else:
            in_bin = (y_prob >= lo) & (y_prob <= hi)

        count = int(in_bin.sum())
        if count == 0:
            continue

        mean_pred = float(y_prob[in_bin].mean())
        actual_frac = float(y_true[in_bin].mean())
        bins_result.append(CalibrationBin(
            bin_low=round(lo, 4),
            bin_high=round(hi, 4),
            mean_predicted=round(mean_pred, 4),
            actual_fraction=round(actual_frac, 4),
            count=count,
        ))

    return bins_result


def expected_calibration_error(
    y_true: pd.Series | np.ndarray,
    y_prob: pd.Series | np.ndarray,
    n_bins: int = 10,
) -> float:
    """
    Expected Calibration Error (ECE).

    Weighted average of the absolute gap between predicted probability and
    empirical win rate, with each bin weighted by its sample count.

    ECE = sum_bins( (count_bin / total) * |actual_fraction_bin - mean_pred_bin| )

    A perfectly calibrated model has ECE = 0. Values above 0.05 indicate
    meaningful miscalibration.

    Args:
        y_true: Binary outcomes.
        y_prob: Predicted probabilities.
        n_bins: Number of bins.

    Returns:
        Scalar ECE in [0, 1], or nan if no valid samples.
    """
    y_true = np.asarray(y_true, dtype=float)
    y_prob = np.asarray(y_prob, dtype=float)

    mask = ~(np.isnan(y_true) | np.isnan(y_prob))
    total = int(mask.sum())
    if total == 0:
        return float("nan")

    bins = calibration_bins(y_true, y_prob, n_bins=n_bins)
    ece = sum(b.count / total * b.abs_gap for b in bins)
    return round(ece, 6)


def format_calibration_report(
    bins: list[CalibrationBin],
    model_name: str = "",
) -> str:
    """
    Format calibration bins as a human-readable ASCII table.

    Args:
        bins:       List of CalibrationBin objects from calibration_bins().
        model_name: Optional label for the header.

    Returns:
        Multi-line string suitable for logging or console output.
    """
    header = f"Calibration Report{' — ' + model_name if model_name else ''}"
    lines = [
        header,
        "-" * 60,
        f"{'Bin':>12}  {'Mean Pred':>10}  {'Actual':>8}  {'Gap':>8}  {'Count':>6}",
        "-" * 60,
    ]
    total = sum(b.count for b in bins)
    for b in bins:
        gap_str = f"{b.gap:+.4f}"
        lines.append(
            f"[{b.bin_low:.2f},{b.bin_high:.2f})  "
            f"{b.mean_predicted:>10.4f}  "
            f"{b.actual_fraction:>8.4f}  "
            f"{gap_str:>8}  "
            f"{b.count:>6}"
        )
    lines.append("-" * 60)
    lines.append(f"Total samples: {total}")
    return "\n".join(lines)
