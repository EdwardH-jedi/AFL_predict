"""
models/xgboost_model.py
------------------------
XGBoost gradient-boosted classifier for AFL H2H win prediction.

Uses the same feature set as LogisticBaseline. Supports optional early
stopping via (X_val, y_val) passed to fit().

XGBoost 2.x notes:
  - use_label_encoder removed in 1.6+; omitted here.
  - early_stopping_rounds passed as constructor arg in 2.x.
"""

from __future__ import annotations

import pickle
from pathlib import Path
from typing import Any

import pandas as pd
from loguru import logger

from models.base_model import BaseModel

FEATURE_COLS = [
    "bm_home_implied_prob",
    "bm_away_implied_prob",
    "bm_overround",
    "home_elo_pre",
    "away_elo_pre",
    "elo_diff",
    "home_win_rate_l10",
    "away_win_rate_l10",
    "home_avg_pts_for_l10",
    "away_avg_pts_for_l10",
    "home_avg_pts_against_l10",
    "away_avg_pts_against_l10",
    "home_rest_days",
    "away_rest_days",
    "is_final",
]


class XGBoostModel(BaseModel):
    """XGBoost win probability model with optional early stopping."""

    name = "xgboost"
    version = "0.1"

    def __init__(
        self,
        n_estimators: int = 300,
        max_depth: int = 4,
        learning_rate: float = 0.05,
        subsample: float = 0.8,
        colsample_bytree: float = 0.8,
        early_stopping_rounds: int = 20,
        random_state: int = 42,
    ) -> None:
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.learning_rate = learning_rate
        self.subsample = subsample
        self.colsample_bytree = colsample_bytree
        self.early_stopping_rounds = early_stopping_rounds
        self.random_state = random_state
        self._model = None
        self._fit_features: list[str] = []

    def fit(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        X_val: pd.DataFrame | None = None,
        y_val: pd.Series | None = None,
    ) -> None:
        from xgboost import XGBClassifier

        available = [col for col in FEATURE_COLS if col in X.columns]
        if not available:
            raise ValueError(
                f"XGBoostModel.fit: no expected feature columns found. Have: {list(X.columns)}"
            )
        self._fit_features = available

        X_feat = _prep(X[available])
        mask = X_feat.notna().all(axis=1) & y.notna()
        X_tr = X_feat[mask].values
        y_tr = y[mask].astype(int).values

        eval_set = None
        if X_val is not None and y_val is not None:
            av_val = [c for c in available if c in X_val.columns]
            X_v = _prep(X_val[av_val]).fillna(0.5).values
            y_v = y_val.reset_index(drop=True).astype(int).values
            eval_set = [(X_v, y_v)]

        self._model = XGBClassifier(
            n_estimators=self.n_estimators,
            max_depth=self.max_depth,
            learning_rate=self.learning_rate,
            subsample=self.subsample,
            colsample_bytree=self.colsample_bytree,
            random_state=self.random_state,
            eval_metric="logloss",
            verbosity=0,
            early_stopping_rounds=self.early_stopping_rounds if eval_set else None,
        )
        fit_kwargs: dict[str, Any] = {}
        if eval_set is not None:
            fit_kwargs["eval_set"] = eval_set
            fit_kwargs["verbose"] = False

        self._model.fit(X_tr, y_tr, **fit_kwargs)
        best = getattr(self._model, "best_iteration", None)
        logger.info(
            f"XGBoostModel.fit(): {len(X_tr)} samples, {len(available)} features"
            + (f", best_iteration={best}" if best is not None else "")
        )

    def predict_proba(self, X: pd.DataFrame) -> pd.DataFrame:
        if self._model is None:
            raise RuntimeError("XGBoostModel: not fitted. Call fit() first.")
        available = [c for c in self._fit_features if c in X.columns]
        X_pred = _prep(X[available]).fillna(0.5).values
        probs = self._model.predict_proba(X_pred)
        result = X[["match_id"]].copy().reset_index(drop=True)
        result["home_win_prob"] = probs[:, 1].round(6)
        result["away_win_prob"] = probs[:, 0].round(6)
        return result

    def save(self, artifacts_dir: str | Path) -> Path:
        if self._model is None:
            raise RuntimeError("Cannot save unfitted XGBoostModel.")
        path = Path(artifacts_dir) / f"{self.name}_{self.version}.pkl"
        with open(path, "wb") as f:
            pickle.dump({"model": self._model, "features": self._fit_features}, f)
        logger.info(f"XGBoostModel saved to {path}")
        return path

    def load(self, artifacts_dir: str | Path) -> None:
        path = Path(artifacts_dir) / f"{self.name}_{self.version}.pkl"
        with open(path, "rb") as f:
            data = pickle.load(f)
        self._model = data["model"]
        self._fit_features = data["features"]

    def metadata(self) -> dict[str, Any]:
        return {
            **super().metadata(),
            "n_estimators": self.n_estimators,
            "max_depth": self.max_depth,
            "learning_rate": self.learning_rate,
        }


def _prep(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "is_final" in out.columns:
        out["is_final"] = out["is_final"].astype(float)
    return out
