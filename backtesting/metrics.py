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

    # Raw counts retained so pooled aggregates are exact rather than
    # back-derived from a rounded rate (see aggregate_metrics).
    n_bets_settled: int = 0   # bets with a recorded outcome
    n_bets_won: int = 0       # of those, how many won
    edge_sum: float = 0.0     # sum of edges over placed bets

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
    n_bets_settled = 0
    n_bets_won = 0
    edge_sum = 0.0
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
            n_bets_settled = int(len(settled_bets))
            n_bets_won = int(settled_bets["won"].astype(bool).sum()) if n_bets_settled else 0
            hit_rate = (
                round(float(settled_bets["won"].mean()), 6)
                if n_bets_settled > 0
                else math.nan
            )
        else:
            hit_rate = math.nan

        # avg_edge
        if n_bets > 0 and "edge" in simulated_bets.columns:
            edge_sum = float(simulated_bets["edge"].sum())
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
        n_bets_settled=n_bets_settled,
        n_bets_won=n_bets_won,
        edge_sum=edge_sum,
        hit_rate=hit_rate,
        avg_edge=avg_edge,
        total_staked=total_staked,
        roi=roi,
    )


def aggregate_metrics(
    window_results: list[WindowMetrics],
    pooled_predictions: pd.DataFrame | None = None,
    n_bins: int = 10,
) -> dict:
    """
    Aggregate per-fold metrics into a single summary for one model.

    **Which aggregations are exact, and which are not.**

    Brier score, log loss and accuracy are means of per-row quantities, so a
    fold-mean weighted by `n_settled` is *identical* to computing them over all
    pooled rows. `_wavg` is exact for those three.

    ECE is not like that. It bins predictions and compares each bin's mean
    prediction to its empirical rate, so it is **not decomposable**: a weighted
    average of per-season ECE is a different statistic from ECE over the pooled
    predictions, and on this dataset the two disagree enough to reverse the
    calibration ranking. Small per-season samples (~200 matches over 10 bins)
    also bias each seasonal estimate upward, which the weighted average then
    carries into the aggregate.

    Both are therefore reported under explicit names and never as bare "ece":

      pooled_ece           ECE over every prediction from every fold at once.
                           The canonical figure for a global calibration claim.
                           Requires `pooled_predictions`; None without it.
      season_weighted_ece  n_settled-weighted mean of per-season ECE. Retained
                           as a macro/seasonal diagnostic only.

    Decision metrics follow the same rule. `pooled_hit_rate` is total wins over
    total settled bets; `macro_season_hit_rate` is the unweighted fold mean that
    earlier versions reported as plain "hit_rate". Both are named explicitly.

    Args:
        window_results:     Per-fold metrics for one model.
        pooled_predictions: Optional frame with columns `y_true` and `y_prob`
                            covering every settled prediction the model made
                            across all folds. Required for pooled_ece.
        n_bins:             Bin count for pooled ECE (must match per-fold usage).
    """
    if not window_results:
        return {}

    total_settled = sum(w.n_settled for w in window_results)
    total_bets = sum(w.n_bets for w in window_results)
    total_no_bet = sum(w.n_no_bet for w in window_results)
    total_staked_sum = sum(w.total_staked for w in window_results)
    total_bets_settled = sum(w.n_bets_settled for w in window_results)
    total_bets_won = sum(w.n_bets_won for w in window_results)
    total_edge_sum = sum(w.edge_sum for w in window_results)

    def _wavg(attr: str) -> float:
        """n_settled-weighted mean. Exact for Brier, log loss and accuracy."""
        vals = [(getattr(w, attr), w.n_settled) for w in window_results
                if not math.isnan(getattr(w, attr)) and w.n_settled > 0]
        if not vals:
            return math.nan
        total_w = sum(wt for _, wt in vals)
        return round(sum(v * wt for v, wt in vals) / total_w, 6) if total_w > 0 else math.nan

    def _macro(attr: str) -> float:
        """Unweighted mean across folds. A macro statistic, not a pooled one."""
        vals = [getattr(w, attr) for w in window_results if not math.isnan(getattr(w, attr))]
        return round(float(np.mean(vals)), 6) if vals else math.nan

    # --- Calibration: pooled is canonical, season-weighted is diagnostic ---
    pooled_ece: float | None = None
    if pooled_predictions is not None and not pooled_predictions.empty:
        valid = pooled_predictions.dropna(subset=["y_true", "y_prob"])
        if len(valid) > 0:
            pooled_ece = expected_calibration_error(
                valid["y_true"].values, valid["y_prob"].values, n_bins=n_bins
            )
    season_weighted_ece = _wavg("ece")

    # Aggregate ROI: total profit / total staked across all folds
    all_roi_nan = all(math.isnan(w.roi) for w in window_results)
    if all_roi_nan or total_staked_sum == 0:
        agg_roi = math.nan
    else:
        profits = [w.roi * w.total_staked for w in window_results
                   if not math.isnan(w.roi) and w.total_staked > 0]
        agg_roi = round(sum(profits) / total_staked_sum, 6) if total_staked_sum > 0 else math.nan

    pooled_hit_rate = (
        round(total_bets_won / total_bets_settled, 6) if total_bets_settled > 0 else math.nan
    )
    pooled_avg_edge = round(total_edge_sum / total_bets, 6) if total_bets > 0 else math.nan

    return {
        "model_name": window_results[0].model_name,
        "n_folds": len(window_results),
        "n_settled_total": total_settled,

        # Exact pooled equivalents (mean-of-means weighted by n is identical here)
        "brier_score": _wavg("brier_score"),
        "log_loss": _wavg("log_loss"),
        "accuracy": _wavg("accuracy"),

        # Calibration — two distinct statistics, never a bare "ece"
        "pooled_ece": pooled_ece,
        "season_weighted_ece": season_weighted_ece,

        # Decision metrics — pooled and macro reported side by side
        "n_bets_total": total_bets,
        "n_no_bet_total": total_no_bet,
        "n_bets_settled_total": total_bets_settled,
        "n_bets_won_total": total_bets_won,
        "pooled_hit_rate": pooled_hit_rate,
        "macro_season_hit_rate": _macro("hit_rate"),
        "pooled_avg_edge": pooled_avg_edge,
        "macro_season_avg_edge": _macro("avg_edge"),
        "edge_sum_total": round(total_edge_sum, 6),
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
