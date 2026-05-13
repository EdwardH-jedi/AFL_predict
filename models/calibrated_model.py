"""
models/calibrated_model.py
---------------------------
Post-hoc isotonic regression calibration wrapper.

Wraps any fitted BaseModel and applies a per-model IsotonicRegression
calibrator trained on a held-out calibration set.

Usage:
    # After fitting the base model:
    cal_model = CalibratedModel(base_model)
    cal_model.calibrate(X_cal, y_cal)   # fit isotonic on held-out set
    preds = cal_model.predict_proba(X)  # calibrated probs

    # Save/load bundles both the base model artifact and the calibrator:
    cal_model.save(artifacts_dir)
    cal_model.load(artifacts_dir)

Design notes:
  - Calibration is one-dimensional: maps raw home_win_prob → calibrated prob.
  - IsotonicRegression is monotone by construction, so P(A) + P(B) ≤ 1 is not
    guaranteed after calibration. We renormalise: away_win_prob = 1 - home_win_prob.
  - A minimum of 30 calibration samples is recommended for isotonic regression;
    below this, calibration is skipped with a warning and raw probs are returned.
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


class CalibratedModel(BaseModel):
    """
    Wrapper that adds isotonic regression calibration to any BaseModel.
    """

    def __init__(self, base_model: BaseModel) -> None:
        self._base = base_model
        self._calibrator: IsotonicRegression | None = None
        self._calibrated = False

    # Proxy name/version to the wrapped model so DB records are consistent
    @property
    def name(self) -> str:  # type: ignore[override]
        return self._base.name

    @property
    def version(self) -> str:  # type: ignore[override]
        return self._base.version

    def fit(self, X: pd.DataFrame, y: pd.Series, **kwargs) -> None:
        """Delegate fit to the base model."""
        self._base.fit(X, y, **kwargs)

    def calibrate(self, X_cal: pd.DataFrame, y_cal: pd.Series) -> None:
        """
        Fit the isotonic calibrator on a held-out calibration set.

        Args:
            X_cal: Feature DataFrame for calibration matches.
            y_cal: Binary series (1 = home win, 0 = away win).
        """
        mask = y_cal.notna()
        if mask.sum() < 30:
            logger.warning(
                f"CalibratedModel({self.name}): only {mask.sum()} calibration samples — "
                "skipping calibration (need ≥ 30). Raw probabilities will be used."
            )
            return

        raw_preds = self._base.predict_proba(X_cal[mask])
        y_prob = raw_preds["home_win_prob"].values
        y_true = y_cal[mask].astype(int).values

        self._calibrator = IsotonicRegression(out_of_bounds="clip")
        self._calibrator.fit(y_prob, y_true)
        self._calibrated = True

        # Report ECE improvement
        from backtesting.calibration import expected_calibration_error
        ece_before = expected_calibration_error(y_true, y_prob)
        cal_prob = self._calibrator.predict(y_prob)
        ece_after = expected_calibration_error(y_true, cal_prob)
        logger.info(
            f"CalibratedModel({self.name}): calibrated on {mask.sum()} samples. "
            f"ECE: {ece_before:.4f} → {ece_after:.4f}"
        )

    def predict_proba(self, X: pd.DataFrame) -> pd.DataFrame:
        """Return calibrated win probabilities."""
        result = self._base.predict_proba(X)
        if not self._calibrated or self._calibrator is None:
            return result

        raw_home = result["home_win_prob"].values
        cal_home = np.clip(self._calibrator.predict(raw_home), 1e-6, 1 - 1e-6)
        result = result.copy()
        result["home_win_prob"] = cal_home.round(6)
        result["away_win_prob"] = (1.0 - cal_home).round(6)
        return result

    def save(self, artifacts_dir: str | Path) -> Path:
        """Save base model artifact + calibrator in a single bundle."""
        base_path = self._base.save(artifacts_dir)
        cal_path = Path(artifacts_dir) / f"{self.name}_{self.version}_calibrator.pkl"
        with open(cal_path, "wb") as f:
            pickle.dump({"calibrator": self._calibrator, "calibrated": self._calibrated}, f)
        logger.info(f"CalibratedModel({self.name}): calibrator saved to {cal_path}")
        return base_path

    def load(self, artifacts_dir: str | Path) -> None:
        """Load base model artifact + calibrator."""
        self._base.load(artifacts_dir)
        cal_path = Path(artifacts_dir) / f"{self.name}_{self.version}_calibrator.pkl"
        if cal_path.exists():
            with open(cal_path, "rb") as f:
                data = pickle.load(f)
            self._calibrator = data["calibrator"]
            self._calibrated = data["calibrated"]
            logger.info(f"CalibratedModel({self.name}): calibrator loaded from {cal_path}")
        else:
            logger.warning(
                f"CalibratedModel({self.name}): no calibrator file at {cal_path}. "
                "Using raw probabilities."
            )

    def metadata(self) -> dict[str, Any]:
        meta = self._base.metadata()
        meta["calibrated"] = self._calibrated
        return meta
