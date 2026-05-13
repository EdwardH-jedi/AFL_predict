"""
backtesting/xgb_tuner.py
-------------------------
Grid search over XGBoost hyperparameters using expanding-window walk-forward
validation. Saves best params to storage/xgb_best_params.json.

Uses only the last N folds (default 5) because early folds have few rows
and XGBoost needs sufficient data to show its advantage.

Usage:
    python -m backtesting.xgb_tuner
    python -m backtesting.xgb_tuner --folds 5
"""

from __future__ import annotations

import argparse
import json
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger
from sklearn.metrics import brier_score_loss

from backtesting.splits import expanding_window_splits
from config.settings import get_settings
from models.xgboost_model import FEATURE_COLS, XGBoostModel

settings = get_settings()
FEATURES_DIR = Path(settings.raw_snapshots_dir) / "features"
OUTPUT_PATH = Path(settings.model_artifacts_dir) / "xgb_best_params.json"

# ---------------------------------------------------------------------------
# Search grid
# ---------------------------------------------------------------------------
MAX_DEPTH_VALUES = [3, 4, 5, 6]
LEARNING_RATE_VALUES = [0.01, 0.03, 0.05, 0.10]
N_ESTIMATORS_VALUES = [200, 300, 500]
SUBSAMPLE_VALUES = [0.7, 0.8, 0.9]

# Limit iterations during tuning for speed (early stopping handles over-training)
_TUNE_EARLY_STOPPING = 20


def run(last_n_folds: int = 5) -> dict:
    """
    Run XGBoost hyperparameter grid search.

    Returns:
        Dict with best params suitable for XGBoostModel(**params).
    """
    df = _load_features()
    if df is None:
        raise RuntimeError("xgb_tuner: no feature parquet found. Run build_features first.")

    settled = df[df["home_win"].notna()].sort_values("match_time").copy()
    splits = expanding_window_splits(settled, min_train_seasons=2)
    if not splits:
        raise RuntimeError("xgb_tuner: not enough seasons.")

    # Only use the most recent folds — early folds have too few rows for XGBoost
    splits = splits[-last_n_folds:]

    grid = list(
        product(MAX_DEPTH_VALUES, LEARNING_RATE_VALUES, N_ESTIMATORS_VALUES, SUBSAMPLE_VALUES)
    )
    logger.info(
        f"xgb_tuner: grid search over {len(grid)} combinations across {len(splits)} folds."
    )

    results: list[tuple[float, dict]] = []

    for depth, lr, n_est, sub in grid:
        fold_briers: list[tuple[float, int]] = []

        for train_df, test_df in splits:
            y_train = train_df["home_win"].astype(int)
            y_test = test_df["home_win"].astype(int)
            X_train = train_df.drop(columns=["home_win"])
            X_test = test_df.drop(columns=["home_win"])

            # Check we have enough feature coverage in this fold
            available = [c for c in FEATURE_COLS if c in X_train.columns]
            if len(available) < 5:
                continue

            model = XGBoostModel(
                n_estimators=n_est,
                max_depth=depth,
                learning_rate=lr,
                subsample=sub,
                colsample_bytree=0.8,
                early_stopping_rounds=_TUNE_EARLY_STOPPING,
            )
            try:
                model.fit(X_train, y_train, X_val=X_test, y_val=y_test)
            except Exception as exc:
                logger.debug(f"xgb_tuner: fit failed (depth={depth}, lr={lr}): {exc}")
                continue

            preds = model.predict_proba(X_test)
            y_prob = preds["home_win_prob"].values
            y_true = y_test.values
            valid = ~(np.isnan(y_true) | np.isnan(y_prob))
            if valid.sum() < 5:
                continue

            b = float(brier_score_loss(y_true[valid], y_prob[valid]))
            fold_briers.append((b, int(valid.sum())))

        if not fold_briers:
            continue

        total_n = sum(n for _, n in fold_briers)
        wmean = sum(b * n for b, n in fold_briers) / total_n
        params = {
            "max_depth": depth,
            "learning_rate": lr,
            "n_estimators": n_est,
            "subsample": sub,
        }
        results.append((wmean, params))

    if not results:
        raise RuntimeError("xgb_tuner: no valid results — check feature coverage.")

    results.sort(key=lambda x: x[0])
    best_brier, best_params = results[0]

    logger.info(
        f"xgb_tuner: best params — {best_params} (brier={best_brier:.5f})"
    )
    logger.info("xgb_tuner: top 5 combinations:")
    for brier, params in results[:5]:
        logger.info(f"  {params}  → brier={brier:.5f}")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(best_params, indent=2))
    logger.info(f"xgb_tuner: saved best params to {OUTPUT_PATH}")
    return best_params


def _load_features() -> pd.DataFrame | None:
    files = sorted(FEATURES_DIR.glob("features*.parquet"), key=lambda p: p.stat().st_mtime)
    if not files:
        return None
    return pd.read_parquet(files[-1])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--folds", type=int, default=5)
    args = parser.parse_args()
    run(last_n_folds=args.folds)
