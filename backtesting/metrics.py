"""
backtesting/metrics.py
-----------------------
Evaluation metric functions for probability forecasts and paper-trade results.

All functions are pure — they operate on arrays/DataFrames and return
numeric results. No model fitting or I/O occurs here.

Metrics tracked:
  Probability quality:
    - Brier score      (lower = better; 0.25 = uninformative coin-flip baseline)
    - Log loss         (lower = better)
    - Accuracy         (fraction of matches where model's top pick was correct)
    - ECE              (expected calibration error; lower = better calibration)

  Decision quality (requires recommendation simulation output):
    - n_bets           (number of matches where a bet was recommended)
    - n_no_bet         (matches skipped because edge was below threshold)
    - hit_rate         (fraction of recommended bets where the picked side won)
    - avg_edge         (mean model_prob - bm_implied_prob for bet matches)
    - total_staked     (sum of kelly fractions for all bets — virtual unit)
    - roi              (net profit / total staked; negative = losing strategy)
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, log_loss

from backtesting.calibration import expected_calibration_error

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class WindowMetrics:
    """Evaluation metrics for one model on one backtest fold."""
    model_name: str
    fold_label: str           # e.g. "2023" or "2022–2023"

    # Match counts
    n_matches: int            # total matches in the test window
    n_settled: int            # matches with a recorded result

    # Probability quality
    brier_score: float        # lower = better (0.25 = coin-flip baseline)
    log_loss: float           # lower = better
    accuracy: float           # fraction predicted correctly (threshold = 0.5)
    ece: float                # expected calibration error

    # Decision quality
    n_bets: int               # number of bet recommendations
    n_no_bet: int             # number of matches skipped
    hit_rate: float           # fraction of bets that won (nan if n_bets=0)
    avg_edge: float           # mean(model_prob - bm_implied_prob) for placed bets
    total_staked: float       # sum of stake_fractions (virtual unit)
    roi: float                # net profit / total_staked (nan if total_staked=0)

    def to_dict(self) -> dict:
        return {
            "model_name": self.model_name,
            "fold_label": self.fold_label,
            "n_matches": self.n_matches,
            "n_settled": self.n_settled,
            "brier_score": _fmt(self.brier_score),
            "log_loss": _fmt(self.log_loss),
            "accuracy": _fmt(self.accuracy),
            "ece": _fmt(self.ece),
            "n_bets": self.n_bets,
            "n_no_bet": self.n_no_bet,
            "hit_rate": _fmt(self.hit_rate),
            "avg_edge": _fmt(self.avg_edge),
            "total_staked": _fmt(self.total_staked),
            "roi": _fmt(self.roi),
        }


# ---------------------------------------------------------------------------
# Metric computation
# ---------------------------------------------------------------------------

def compute_metrics(
    model_name: str,
    fold_label: str,
    predictions_df: pd.DataFrame,
    actuals: pd.Series,
    simulated_bets: pd.DataFrame | None = None,
) -> WindowMetrics:
    """
    Compute all evaluation metrics for one model on one fold.

    Args:
        model_name:     Label for the model (stored in result).
        fold_label:     Label for the fold/season (stored in result).
        predictions_df: DataFrame with columns [match_id, home_win_prob, away_win_prob].
                        Index must align with `actuals`.
        actuals:        Binary Series (1=home win, 0=away win). NaN for unsettled.
        simulated_bets: Optional DataFrame from backtesting.simulation.simulate_recommendations().
                        Must have columns: [match_id, side, model_prob, bm_implied_prob,
                        stake_fraction, home_win] for ROI calculation.

    Returns:
        WindowMetrics dataclass.
    """
    n_total = len(predictions_df)

    # --- Probability metrics on settled matches only ---
    settled_mask = actuals.notna()
    y_true = actuals[settled_mask].astype(int).values
    y_prob = predictions_df.loc[settled_mask.values, "home_win_prob"].values
    n_settled = int(settled_mask.sum())

    if n_settled < 2:
        brier = math.nan
        ll = math.nan
        acc = math.nan
        ece = math.nan
    else:
        brier = round(float(brier_score_loss(y_true, y_prob)), 6)
        ll = round(float(log_loss(y_true, np.clip(y_prob, 1e-7, 1 - 1e-7), labels=[0, 1])), 6)
        acc = round(float(((y_prob >= 0.5).astype(int) == y_true).mean()), 6)
        ece = round(expected_calibration_error(y_true, y_prob), 6)

    # --- Decision metrics (from simulation output) ---
    if simulated_bets is None or simulated_bets.empty:
        n_bets = 0
        n_no_bet = n_settled
        hit_rate = math.nan
        avg_edge = math.nan
        total_staked = 0.0
        roi = math.nan
    else:
        n_bets = len(simulated_bets)
        n_no_bet = n_settled - n_bets

        # hit_rate: fraction of bets where the recommended side actually won
        if n_bets > 0 and "won" in simulated_bets.columns:
            settled_bets = simulated_bets.dropna(subset=["won"])
            hit_rate = (
                round(float(settled_bets["won"].mean()), 6)
                if len(settled_bets) > 0
                else math.nan
            )
        else:
            hit_rate = math.nan

        # avg_edge
        if n_bets > 0 and "edge" in simulated_bets.columns:
            avg_edge = round(float(simulated_bets["edge"].mean()), 6)
        else:
            avg_edge = math.nan

        # ROI: profit / staked
        total_staked = (
            float(simulated_bets["stake_fraction"].sum())
            if "stake_fraction" in simulated_bets.columns
            else 0.0
        )
        if total_staked > 0 and "profit" in simulated_bets.columns:
            net_profit = float(simulated_bets["profit"].sum())
            roi = round(net_profit / total_staked, 6)
        else:
            roi = math.nan

    return WindowMetrics(
        model_name=model_name,
        fold_label=fold_label,
        n_matches=n_total,
        n_settled=n_settled,
        brier_score=brier,
        log_loss=ll,
        accuracy=acc,
        ece=ece,
        n_bets=n_bets,
        n_no_bet=n_no_bet,
        hit_rate=hit_rate,
        avg_edge=avg_edge,
        total_staked=total_staked,
        roi=roi,
    )


def aggregate_metrics(window_results: list[WindowMetrics]) -> dict:
    """
    Aggregate per-fold metrics across all folds for one model.

    Computes mean (weighted by n_settled) for probability metrics,
    and sum-then-divide for ROI.

    Args:
        window_results: List of WindowMetrics from all folds.

    Returns:
        Dict with aggregated metric values.
    """
    if not window_results:
        return {}

    total_settled = sum(w.n_settled for w in window_results)
    total_bets = sum(w.n_bets for w in window_results)
    total_no_bet = sum(w.n_no_bet for w in window_results)
    total_staked_sum = sum(w.total_staked for w in window_results)

    def _wavg(attr: str) -> float:
        """Weighted average of a metric by n_settled."""
        vals = [(getattr(w, attr), w.n_settled) for w in window_results
                if not math.isnan(getattr(w, attr)) and w.n_settled > 0]
        if not vals:
            return math.nan
        total_w = sum(wt for _, wt in vals)
        return round(sum(v * wt for v, wt in vals) / total_w, 6) if total_w > 0 else math.nan

    def _bet_avg(attr: str) -> float:
        """Average of a bet metric across non-nan folds."""
        vals = [getattr(w, attr) for w in window_results if not math.isnan(getattr(w, attr))]
        return round(float(np.mean(vals)), 6) if vals else math.nan

    # Aggregate ROI: total profit / total staked across all folds
    all_roi_nan = all(math.isnan(w.roi) for w in window_results)
    if all_roi_nan or total_staked_sum == 0:
        agg_roi = math.nan
    else:
        # Re-derive total profit from roi * staked per fold
        profits = [w.roi * w.total_staked for w in window_results
                   if not math.isnan(w.roi) and w.total_staked > 0]
        agg_roi = round(sum(profits) / total_staked_sum, 6) if total_staked_sum > 0 else math.nan

    return {
        "model_name": window_results[0].model_name,
        "n_folds": len(window_results),
        "n_settled_total": total_settled,
        "brier_score": _wavg("brier_score"),
        "log_loss": _wavg("log_loss"),
        "accuracy": _wavg("accuracy"),
        "ece": _wavg("ece"),
        "n_bets_total": total_bets,
        "n_no_bet_total": total_no_bet,
        "hit_rate": _bet_avg("hit_rate"),
        "avg_edge": _bet_avg("avg_edge"),
        "total_staked": round(total_staked_sum, 6),
        "roi": agg_roi,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt(v: float) -> float | None:
    """Convert nan to None for clean JSON serialisation."""
    if math.isnan(v):
        return None
    return v
