"""
models/logistic_baseline.py
----------------------------
Logistic regression baseline model.

Trains a scikit-learn LogisticRegression on the feature matrix produced by
DatasetBuilder. This is intentionally simple — the purpose is a stable,
interpretable benchmark, not a state-of-the-art classifier.

All features are pre-computed by the feature extractor layer and are
guaranteed to be pre-match (no leakage by construction).

TODO: Tune regularisation strength C on a held-out season once sufficient
      historical data is available.
TODO: Add cross-validated calibration check before any live use.
"""

import pickle
from pathlib import Path
from typing import Any

import pandas as pd
from loguru import logger
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from models.base_model import BaseModel

# All pre-match features available from the DatasetBuilder.
# Missing columns are handled gracefully — the model trains on whatever subset
# is present. Features are listed in rough order of expected informativeness.
FEATURE_COLS = [
    # Bookmaker market — best single predictor in most sports
    "bm_home_implied_prob",
    "bm_away_implied_prob",
    "bm_overround",
    # ELO ratings computed by EloExtractor (pre-match, no leakage)
    "home_elo_pre",
    "away_elo_pre",
    "elo_diff",
    # Rolling form — last 10 games per team
    "home_win_rate_l10",
    "away_win_rate_l10",
    "home_avg_pts_for_l10",
    "away_avg_pts_for_l10",
    "home_avg_pts_against_l10",
    "away_avg_pts_against_l10",
    # Rest days
    "home_rest_days",
    "away_rest_days",
    # Match context
    "is_final",
]


class LogisticBaseline(BaseModel):
    """
    Logistic regression win probability model.

    Input features are standardised. Missing values are dropped during fit
    and imputed to 0.5 during prediction (no-information prior for probs).
    """

    name = "logistic_baseline"
    version = "0.1"

    def __init__(self, C: float = 1.0, max_iter: int = 1000) -> None:
        self.C = C
        self.max_iter = max_iter
        self.pipeline: Pipeline | None = None

    def fit(self, X: pd.DataFrame, y: pd.Series) -> None:
        """
        Fit logistic regression pipeline.

        Args:
            X: Feature DataFrame — must contain at least some of FEATURE_COLS.
               Rows with any NaN in the selected features are dropped.
            y: Binary target (1 = home win, 0 = away win).
        """
        available = [col for col in FEATURE_COLS if col in X.columns]
        if not available:
            raise ValueError(
                f"LogisticBaseline: none of the expected feature columns found in "
                f"DataFrame. Have: {list(X.columns)}. Expected subset of: {FEATURE_COLS}."
            )

        # Store which features were used so predict_proba uses the same set
        self._fit_features = available

        X_feat = X[available].copy()
        # is_final is boolean — convert to int so StandardScaler handles it
        if "is_final" in X_feat.columns:
            X_feat["is_final"] = X_feat["is_final"].astype(float)

        # Drop rows where any selected feature or target is missing
        mask = X_feat.notna().all(axis=1) & y.notna()
        X_train = X_feat[mask]
        y_train = y[mask]

        if len(X_train) < 20:
            logger.warning(
                f"LogisticBaseline: only {len(X_train)} clean training samples — "
                "results will be unreliable."
            )

        self.pipeline = Pipeline([
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression(C=self.C, max_iter=self.max_iter, random_state=42)),
        ])
        self.pipeline.fit(X_train, y_train)
        logger.info(
            f"LogisticBaseline.fit(): trained on {len(X_train)} samples "
            f"using {len(available)} features: {available}."
        )

    def predict_proba(self, X: pd.DataFrame) -> pd.DataFrame:
        """Return predicted win probabilities for each match."""
        if self.pipeline is None:
            raise RuntimeError("LogisticBaseline: model is not fitted. Call fit() first.")

        # Use the exact features that were fitted
        fit_cols = getattr(self, "_fit_features", [col for col in FEATURE_COLS if col in X.columns])
        available = [col for col in fit_cols if col in X.columns]
        X_pred = X[available].copy()
        if "is_final" in X_pred.columns:
            X_pred["is_final"] = X_pred["is_final"].astype(float)
        X_pred = X_pred.fillna(0.5)  # impute missing with no-info prior

        probs = self.pipeline.predict_proba(X_pred)
        # sklearn returns [P(class=0), P(class=1)] — class=1 is home win
        result = X[["match_id"]].copy()
        result["home_win_prob"] = probs[:, 1].round(6)
        result["away_win_prob"] = probs[:, 0].round(6)
        return result.reset_index(drop=True)

    def save(self, artifacts_dir: str | Path) -> Path:
        if self.pipeline is None:
            raise RuntimeError("Cannot save unfitted model.")
        path = Path(artifacts_dir) / f"{self.name}_{self.version}.pkl"
        with open(path, "wb") as f:
            pickle.dump(self.pipeline, f)
        logger.info(f"LogisticBaseline saved to {path}")
        return path

    def load(self, artifacts_dir: str | Path) -> None:
        path = Path(artifacts_dir) / f"{self.name}_{self.version}.pkl"
        with open(path, "rb") as f:
            self.pipeline = pickle.load(f)
        logger.info(f"LogisticBaseline loaded from {path}")

    def metadata(self) -> dict[str, Any]:
        return {**super().metadata(), "C": self.C, "max_iter": self.max_iter}
