"""
models/bookmaker_baseline.py
-----------------------------
Bookmaker baseline model.

Uses the bookmaker's own implied probabilities (overround-adjusted) as the
prediction. This is the hardest baseline to beat — any model that can't
outperform the bookmaker on calibration metrics is not worth deploying.

No training required. predict_proba() reads bm_home_implied_prob directly.
"""

import pandas as pd
from loguru import logger

from models.base_model import BaseModel


class BookmakerBaseline(BaseModel):
    """
    Passthrough model: returns bookmaker implied probabilities as predictions.

    Serves as the performance ceiling baseline. A model must demonstrably
    beat this on out-of-sample Brier score / log loss before being considered.
    """

    name = "bookmaker_baseline"
    version = "0.1"

    def fit(self, X: pd.DataFrame, y: pd.Series) -> None:
        """No training needed — this model is purely derived from market odds."""
        logger.info("BookmakerBaseline.fit(): no-op (market-derived model).")

    def predict_proba(self, X: pd.DataFrame) -> pd.DataFrame:
        """
        Return the bookmaker's own implied probabilities.

        Requires columns: match_id, bm_home_implied_prob, bm_away_implied_prob
        Rows with missing odds are filled with 0.5 / 0.5 (no-information prior).
        """
        required = {"match_id", "bm_home_implied_prob", "bm_away_implied_prob"}
        missing = required - set(X.columns)
        if missing:
            raise ValueError(f"BookmakerBaseline: missing columns {missing}")

        result = X[["match_id"]].copy()
        result["home_win_prob"] = X["bm_home_implied_prob"].fillna(0.5)
        result["away_win_prob"] = X["bm_away_implied_prob"].fillna(0.5)

        # Sanity check: probs should sum to ~1.0 (they are already normalised)
        prob_sum = result["home_win_prob"] + result["away_win_prob"]
        if (prob_sum - 1.0).abs().max() > 0.01:
            logger.warning("BookmakerBaseline: probabilities do not sum to 1.0 — check inputs.")

        return result.reset_index(drop=True)
