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


class TrainableEnsemble(Ensemble):
    """
    Ensemble that fits its own components, so it can be evaluated in a backtest.

    The production ensemble (orchestration/jobs/generate_recommendations.py)
    wraps components that were already fitted and persisted by train_models.
    A walk-forward backtest has no such artifacts: BacktestRunner calls fit()
    on every model once per fold. This subclass bridges that gap by forwarding
    fit() to each component, which is what makes the blend measurable on the
    same folds and metrics as its parts.

    Weights are supplied by the caller and should come from
    Settings.ensemble_weights — the single source of truth — so the blend that
    gets benchmarked is the blend that ships.
    """

    name = "ensemble"

    def __init__(self, components: list[tuple[BaseModel, float]]) -> None:
        super().__init__(components)
        # The canonical roster, normalised once and never mutated. fit() derives
        # a per-fold active set from this rather than editing it in place.
        #
        # Why this matters: BacktestRunner reuses one ensemble instance across
        # every fold. The previous implementation assigned the survivors back to
        # self.components, so a component that failed to fit in fold 1 was gone
        # from folds 2..N permanently — one transient failure silently changed
        # the model being evaluated for the rest of the run.
        self._canonical: list[tuple[BaseModel, float]] = list(self.components)
        # Per-fold audit trail: [{"n_components", "weights"}], appended by fit().
        self.fold_compositions: list[dict[str, Any]] = []

    @property
    def canonical_weights(self) -> dict[str, float]:
        """The full roster's weights, independent of any fold's failures."""
        return {m.name: w for m, w in self._canonical}

    def fit(self, X: pd.DataFrame, y: pd.Series) -> None:
        """
        Fit every component on the fold's training data.

        A component that fails to fit is dropped **for this fold only**, then
        the surviving weights are renormalised so the blend stays a proper
        average. That mirrors how predict_proba() renormalises over components
        that actually responded, and keeps one unavailable optional dependency
        (e.g. XGBoost without its OpenMP runtime) from blanking the ensemble row
        of an entire backtest.

        The canonical roster is restored at the start of every call, so a
        failure in one fold cannot leak into the next.
        """
        # Restore the full roster before each fold — this is the fix.
        self.components = list(self._canonical)

        fitted = []
        for model, weight in self._canonical:
            try:
                model.fit(X, y)
            except Exception as exc:
                logger.warning(
                    f"TrainableEnsemble.fit(): {model.name} fit failed ({exc}) — "
                    "dropping it from THIS fold's blend only."
                )
                continue
            fitted.append((model, weight))

        if not fitted:
            raise RuntimeError("TrainableEnsemble.fit(): every component failed to fit.")

        # Renormalise over the survivors so the blend stays a proper average.
        total = sum(w for _, w in fitted)
        self.components = [(m, w / total) for m, w in fitted]
        self.weights = {m.name: w for m, w in self.components}
        self.fold_compositions.append(
            {"n_components": len(fitted), "weights": dict(self.weights)}
        )
        if len(fitted) < len(self._canonical):
            dropped = sorted({m.name for m, _ in self._canonical} - set(self.weights))
            logger.warning(
                f"TrainableEnsemble.fit(): fold ran with {len(fitted)}/"
                f"{len(self._canonical)} components (dropped: {', '.join(dropped)}). "
                "The full roster is restored for the next fold."
            )
        logger.debug(
            f"TrainableEnsemble.fit(): fitted {len(fitted)} component(s) "
            f"on {len(X)} rows — weights {self.weights}."
        )


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
