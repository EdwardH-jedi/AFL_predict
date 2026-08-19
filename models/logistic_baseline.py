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
from sklearn.impute import SimpleImputer
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
    # ELO ratings computed by EloExtractor (pre-match, no leakage)
    "home_elo_pre",
    "away_elo_pre",
    "elo_diff",
    # Rolling form — multi-window (L3 / L5 / L10)
    "home_win_rate_l3",
    "away_win_rate_l3",
    "home_win_rate_l5",
    "away_win_rate_l5",
    "home_win_rate_l10",
    "away_win_rate_l10",
    "home_avg_pts_for_l10",
    "away_avg_pts_for_l10",
    "home_avg_pts_against_l10",
    "away_avg_pts_against_l10",
    # Momentum: short-term trend vs long-term baseline
    "home_momentum",
    "away_momentum",
    # Head-to-head history
    "h2h_home_win_rate_l5",
    "h2h_avg_margin_l5",
    # Venue-specific performance
    "home_venue_win_rate",
    "away_venue_win_rate",
    "venue_home_advantage",
    # Rest days
    "home_rest_days",
    "away_rest_days",
    # Match context
    "is_final",
    # Interstate travel (4b) — away_interstate_travel and travel_km_diff kept
    "away_interstate_travel",
    "travel_km_diff",
    # Weather (4c) — scoring index and rain signal kept; high_wind pruned
    "weather_scoring_index",
    "weather_is_raining",
]


class LogisticBaseline(BaseModel):
    """
    Logistic regression win probability model.

    Input features are median-imputed then standardised, both inside a fitted
    sklearn Pipeline, so training and prediction impute with the same medians.
    Columns that are entirely null are dropped up front, since median imputation
    has nothing to fill them from. Individual missing values do not drop a row.
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
               Columns that are entirely null are dropped; remaining missing
               values are median-imputed (medians learned at fit time). Rows are
               NOT dropped for individual missing features.
            y: Binary target (1 = home win, 0 = away win).
        """
        available = [col for col in FEATURE_COLS if col in X.columns]
        if not available:
            raise ValueError(
                f"LogisticBaseline: none of the expected feature columns found in "
                f"DataFrame. Have: {list(X.columns)}. Expected subset of: {FEATURE_COLS}."
            )

        X_feat = X[available].copy()
        # is_final is boolean — convert to int so StandardScaler handles it
        if "is_final" in X_feat.columns:
            X_feat["is_final"] = X_feat["is_final"].astype(float)

        # Drop rows where the target is missing
        mask = y.notna()
        X_feat = X_feat[mask]
        y_train = y[mask]

        # Drop columns that are entirely NaN — median imputation cannot fill them
        # and StandardScaler would raise on all-NaN columns.
        all_null_cols = [col for col in X_feat.columns if X_feat[col].isna().all()]
        if all_null_cols:
            logger.warning(
                f"LogisticBaseline: dropping {len(all_null_cols)} all-NaN feature(s): "
                f"{all_null_cols}. These columns will be excluded from this run."
            )
            X_feat = X_feat.drop(columns=all_null_cols)

        available = list(X_feat.columns)
        if not available:
            raise ValueError("LogisticBaseline: all feature columns are NaN — cannot train.")

        # Store the final feature set used so predict_proba uses the same columns
        self._fit_features = available

        if len(X_feat) < 20:
            logger.warning(
                f"LogisticBaseline: only {len(X_feat)} clean training samples — "
                "results will be unreliable."
            )

        self.pipeline = Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression(C=self.C, max_iter=self.max_iter, random_state=42)),
        ])
        # Convert to numpy to avoid pandas/sklearn ndim assertion on mixed-type DataFrames
        self.pipeline.fit(X_feat.to_numpy(), y_train.to_numpy())
        logger.info(
            f"LogisticBaseline.fit(): trained on {len(X_feat)} samples "
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
        probs = self.pipeline.predict_proba(X_pred.to_numpy())
        # sklearn returns [P(class=0), P(class=1)] — class=1 is home win
        result = X[["match_id"]].copy()
        result["home_win_prob"] = probs[:, 1].round(6)
        result["away_win_prob"] = probs[:, 0].round(6)
        return result

    def save(self, artifacts_dir: str | Path) -> Path:
        if self.pipeline is None:
            raise RuntimeError("Cannot save unfitted model.")
        path = Path(artifacts_dir) / f"{self.name}_{self.version}.pkl"
        with open(path, "wb") as f:
            pickle.dump({"pipeline": self.pipeline, "fit_features": self._fit_features}, f)
        logger.info(f"LogisticBaseline saved to {path}")
        return path

    def load(self, artifacts_dir: str | Path) -> None:
        path = Path(artifacts_dir) / f"{self.name}_{self.version}.pkl"
        with open(path, "rb") as f:
            data = pickle.load(f)
        # Support both old format (pipeline only) and new format (dict with fit_features)
        if isinstance(data, dict):
            self.pipeline = data["pipeline"]
            self._fit_features = data["fit_features"]
        else:
            self.pipeline = data
        logger.info(f"LogisticBaseline loaded from {path}")

    def metadata(self) -> dict[str, Any]:
        n_features = len(self._fit_features) if hasattr(self, "_fit_features") else None
        return {
            **super().metadata(),
            "C": self.C,
            "max_iter": self.max_iter,
            "n_features": n_features,
        }
