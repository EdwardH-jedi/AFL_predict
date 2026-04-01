"""
models/ensemble.py
-------------------
Weighted-average ensemble model combining multiple BaseModel instances.
"""
from __future__ import annotations
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd
from loguru import logger
from models.base_model import BaseModel


class Ensemble(BaseModel):
    """
    Weighted average of component models.

    fit() is a no-op: components must already be fitted before wrapping.
    predict_proba() returns the normalised weighted-average probability.
    """

    name = "ensemble"
    version = "0.1"

    def __init__(self, components: list[tuple[BaseModel, float]]) -> None:
        total = sum(w for _, w in components)
        if total <= 0:
            raise ValueError("Ensemble: all component weights are zero.")
        self.components = [(m, w / total) for m, w in components]
        self.weights = {m.name: w / total for m, w in components}

    def fit(self, X: pd.DataFrame, y: pd.Series) -> None:
        """No-op: component models must be fitted before constructing the ensemble."""
        logger.debug("Ensemble.fit(): no-op — component models already fitted.")

    def predict_proba(self, X: pd.DataFrame) -> pd.DataFrame:
        home_sum = np.zeros(len(X))
        away_sum = np.zeros(len(X))
        total_w = 0.0
        for model, weight in self.components:
            if weight <= 0:
                continue
            try:
                preds = model.predict_proba(X).reset_index(drop=True)
                home_sum += preds["home_win_prob"].values * weight
                away_sum += preds["away_win_prob"].values * weight
                total_w += weight
            except Exception as exc:
                logger.warning(f"Ensemble: {model.name} predict_proba failed ({exc}) — skipping.")
        if total_w <= 0:
            raise RuntimeError("Ensemble: all component models failed during predict_proba.")
        result = X[["match_id"]].copy().reset_index(drop=True)
        result["home_win_prob"] = (home_sum / total_w).round(6)
        result["away_win_prob"] = (away_sum / total_w).round(6)
        return result

    def save(self, artifacts_dir) -> Path:
        raise NotImplementedError("Ensemble.save(): save each component model individually.")

    def metadata(self) -> dict[str, Any]:
        return {**super().metadata(), "weights": {m.name: w for m, w in self.components}}


# Alias for import compatibility
EnsembleModel = Ensemble


def optimize_weights(
    components: list[tuple[BaseModel, float]],
    X_val: pd.DataFrame,
    y_val: pd.Series,
) -> dict[str, float]:
    """
    Optimise ensemble weights on a validation set by minimising Brier score.

    Returns a dict {model_name: weight} normalised to sum to 1.
    """
    from scipy.optimize import minimize
    from sklearn.metrics import brier_score_loss

    names = [m.name for m, _ in components]
    preds_list = []
    for model, _ in components:
        p = model.predict_proba(X_val).reset_index(drop=True)
        preds_list.append(p["home_win_prob"].values)

    y_arr = y_val.reset_index(drop=True).astype(int).values
    mask = ~np.isnan(y_arr)

    def brier(w):
        w = np.abs(w) / max(np.abs(w).sum(), 1e-9)
        combined = sum(wi * pi for wi, pi in zip(w, preds_list))
        return brier_score_loss(y_arr[mask], combined[mask])

    x0 = np.array([w for _, w in components], dtype=float)
    res = minimize(brier, x0, method="Nelder-Mead", options={"maxiter": 500, "xatol": 1e-5})
    optimal = np.abs(res.x) / max(np.abs(res.x).sum(), 1e-9)
    result = {name: float(w) for name, w in zip(names, optimal)}
    logger.info(f"optimize_weights: {result}  (Brier={res.fun:.5f})")
    return result
