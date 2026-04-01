"""
models/poisson_model.py
"""
from __future__ import annotations
import pickle
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd
from loguru import logger
from sklearn.isotonic import IsotonicRegression
from models.base_model import BaseModel

_SCORE_COLS = {"home_score", "away_score"}
_MAX_SCORE = 200

FEATURE_COLS_SCALED = [
    "bm_home_implied_prob", "elo_diff",
    "home_win_rate_l10", "away_win_rate_l10",
    "home_rest_days", "away_rest_days", "is_final",
]


class PoissonModel(BaseModel):
    name = "poisson"
    version = "0.1"

    def __init__(self, max_score: int = _MAX_SCORE) -> None:
        self.max_score = max_score
        self._mode: str = "scaled"
        self._home_model = None
        self._away_model = None
        self._iso: IsotonicRegression | None = None
        self._home_mean: float = 90.0
        self._away_mean: float = 85.0

    def fit(self, X: pd.DataFrame, y: pd.Series) -> None:
        has_scores = _SCORE_COLS.issubset(X.columns) and X["home_score"].notna().sum() > 50
        if has_scores:
            self._fit_score_mode(X, y)
        else:
            self._fit_scaled_mode(X, y)

    def predict_proba(self, X: pd.DataFrame) -> pd.DataFrame:
        if self._mode == "score":
            probs = self._predict_score_mode(X)
        else:
            probs = self._predict_scaled_mode(X)
        result = X[["match_id"]].copy().reset_index(drop=True)
        result["home_win_prob"] = np.clip(probs, 0.01, 0.99).round(6)
        result["away_win_prob"] = (1.0 - result["home_win_prob"]).round(6)
        return result

    def save(self, artifacts_dir) -> Path:
        path = Path(artifacts_dir) / f"{self.name}_{self.version}.pkl"
        with open(path, "wb") as f:
            pickle.dump({"mode": self._mode, "home_model": self._home_model,
                         "away_model": self._away_model, "iso": self._iso,
                         "home_mean": self._home_mean, "away_mean": self._away_mean}, f)
        logger.info(f"PoissonModel saved to {path}")
        return path

    def load(self, artifacts_dir) -> None:
        path = Path(artifacts_dir) / f"{self.name}_{self.version}.pkl"
        with open(path, "rb") as f:
            data = pickle.load(f)
        self._mode = data["mode"]; self._home_model = data["home_model"]
        self._away_model = data["away_model"]; self._iso = data["iso"]
        self._home_mean = data["home_mean"]; self._away_mean = data["away_mean"]

    def metadata(self) -> dict[str, Any]:
        return {**super().metadata(), "mode": self._mode, "max_score": self.max_score}

    def _fit_score_mode(self, X, y):
        import statsmodels.api as sm
        mask = X["home_score"].notna() & X["away_score"].notna() & y.notna()
        Xm = X[mask].copy()
        intercept = np.ones(len(Xm))
        is_final = Xm["is_final"].astype(float).values if "is_final" in Xm.columns else np.zeros(len(Xm))
        Xf = np.column_stack([intercept, is_final])
        try:
            self._home_model = sm.GLM(Xm["home_score"].astype(float).values, Xf,
                                      family=sm.families.Poisson()).fit(disp=False)
            self._away_model = sm.GLM(Xm["away_score"].astype(float).values, Xf,
                                      family=sm.families.Poisson()).fit(disp=False)
            self._home_mean = float(Xm["home_score"].mean())
            self._away_mean = float(Xm["away_score"].mean())
            self._mode = "score"
            logger.info(f"PoissonModel.fit(): score_mode on {mask.sum()} matches")
        except Exception as exc:
            logger.warning(f"PoissonModel: score GLM failed ({exc}), falling back to scaled_mode.")
            self._fit_scaled_mode(X, y)

    def _predict_score_mode(self, X):
        if self._home_model is None:
            return np.full(len(X), 0.5)
        is_final = X["is_final"].astype(float).values if "is_final" in X.columns else np.zeros(len(X))
        Xf = np.column_stack([np.ones(len(X)), is_final])
        mu_home = np.maximum(self._home_model.predict(Xf), 1.0)
        mu_away = np.maximum(self._away_model.predict(Xf), 1.0)
        return np.array([_poisson_win_prob(mh, ma, self.max_score) for mh, ma in zip(mu_home, mu_away)])

    def _fit_scaled_mode(self, X, y):
        self._mode = "scaled"
        if "bm_home_implied_prob" not in X.columns:
            return
        mask = X["bm_home_implied_prob"].notna() & y.notna()
        raw = X.loc[mask, "bm_home_implied_prob"].values
        y_true = y[mask].astype(int).values
        if len(raw) < 20:
            return
        self._iso = IsotonicRegression(out_of_bounds="clip")
        self._iso.fit(raw, y_true)
        logger.info(f"PoissonModel.fit(): scaled_mode, {len(raw)} samples")

    def _predict_scaled_mode(self, X):
        if "bm_home_implied_prob" not in X.columns:
            return np.full(len(X), 0.5)
        raw = X["bm_home_implied_prob"].fillna(0.5).values
        if self._iso is not None:
            return self._iso.predict(raw)
        return raw


def _poisson_win_prob(mu_home, mu_away, max_score):
    from scipy.stats import poisson
    k = np.arange(max_score + 1)
    pmf_home = poisson.pmf(k, mu_home)
    cdf_away = poisson.cdf(k - 1, mu_away)
    cdf_away[0] = 0.0
    return float(np.dot(pmf_home, cdf_away))
