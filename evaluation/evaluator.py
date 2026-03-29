"""
evaluation/evaluator.py
------------------------
Compute model evaluation metrics on a set of predictions vs. actual results.

Metrics:
  - Brier Score (lower = better calibrated)
  - Log Loss (lower = better)
  - Accuracy (home win prediction threshold 0.5)
  - ROI on paper trades (requires recommendation + outcome data)
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd
from loguru import logger
from sklearn.metrics import brier_score_loss, log_loss


@dataclass
class EvalResult:
    """Evaluation metrics for one model on one dataset."""
    model_name: str
    n_samples: int
    brier_score: float
    log_loss_score: float
    accuracy: float
    # Paper trade metrics (None if no recommendations)
    total_bets: int | None = None
    roi: float | None = None  # profit / total_staked


class Evaluator:
    """
    Compute and log evaluation metrics for a set of predictions.
    """

    def evaluate(
        self,
        model_name: str,
        predictions_df: pd.DataFrame,
        actuals: pd.Series,
    ) -> EvalResult:
        """
        Evaluate predicted probabilities against actual outcomes.

        Args:
            model_name: Name for logging.
            predictions_df: DataFrame with columns [match_id, home_win_prob].
            actuals: Binary series aligned to predictions_df (1=home win, 0=away win).

        Returns:
            EvalResult with computed metrics.
        """
        # Drop any rows where actuals is NaN (matches not yet played)
        mask = actuals.notna()
        y_true = actuals[mask].astype(int)
        y_prob = predictions_df.loc[mask, "home_win_prob"]

        n = len(y_true)
        if n == 0:
            logger.warning(f"Evaluator: no settled matches for {model_name}.")
            return EvalResult(model_name=model_name, n_samples=0, brier_score=np.nan,
                              log_loss_score=np.nan, accuracy=np.nan)

        brier = brier_score_loss(y_true, y_prob)
        ll = log_loss(y_true, y_prob)
        acc = ((y_prob >= 0.5).astype(int) == y_true).mean()

        result = EvalResult(
            model_name=model_name,
            n_samples=n,
            brier_score=round(brier, 5),
            log_loss_score=round(ll, 5),
            accuracy=round(acc, 5),
        )
        logger.info(
            f"[{model_name}] n={n} brier={result.brier_score} "
            f"logloss={result.log_loss_score} acc={result.accuracy}"
        )
        return result

    def evaluate_roi(
        self,
        recommendations_df: pd.DataFrame,
        outcomes_df: pd.DataFrame,
    ) -> tuple[int, float]:
        """
        Calculate ROI on paper trades.

        Args:
            recommendations_df: Must have columns [id, stake_fraction, recommended_odds].
            outcomes_df: Must have columns [recommendation_id, won].

        Returns:
            (total_bets, roi) where roi = total_profit / total_staked
        """
        merged = recommendations_df.merge(
            outcomes_df, left_on="id", right_on="recommendation_id", how="inner"
        )
        if merged.empty:
            return 0, 0.0

        merged["profit"] = merged.apply(
            lambda r: r["stake_fraction"] * (r["recommended_odds"] - 1)
            if r["won"]
            else -r["stake_fraction"],
            axis=1,
        )
        total_staked = merged["stake_fraction"].sum()
        total_profit = merged["profit"].sum()
        roi = total_profit / total_staked if total_staked > 0 else 0.0

        logger.info(
            f"ROI evaluation: {len(merged)} bets, "
            f"staked={total_staked:.4f}, profit={total_profit:.4f}, ROI={roi:.4f}"
        )
        return len(merged), round(roi, 6)
