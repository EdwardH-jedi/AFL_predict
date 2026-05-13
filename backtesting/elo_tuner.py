"""
backtesting/elo_tuner.py
-------------------------
Grid search over ELO hyperparameters using expanding-window walk-forward
validation. Identifies the (K, home_advantage, season_regression) triple
that minimises mean Brier score across all folds.

Results are saved to storage/elo_best_params.json so train_models.py can
load them without re-running the search every week.

Usage:
    python -m backtesting.elo_tuner
    python -m backtesting.elo_tuner --seasons 5   # only last 5 folds
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
from models.elo_baseline import EloBaseline

settings = get_settings()
FEATURES_DIR = Path(settings.raw_snapshots_dir) / "features"
OUTPUT_PATH = Path(settings.model_artifacts_dir) / "elo_best_params.json"

# ---------------------------------------------------------------------------
# Search grid
# ---------------------------------------------------------------------------
K_VALUES = [16.0, 24.0, 32.0, 40.0]
HA_VALUES = [30.0, 40.0, 50.0, 60.0]
REGRESSION_VALUES = [0.65, 0.70, 0.75, 0.80]


def run(last_n_folds: int | None = None) -> dict:
    """
    Run the grid search and save best params.

    Args:
        last_n_folds: If set, only evaluate on the most recent N folds.
                      Useful when early folds have very few test rows.
    Returns:
        Dict with best params: {"k_factor", "home_advantage", "season_regression"}
    """
    df = _load_features()
    if df is None:
        raise RuntimeError("elo_tuner: no feature parquet found. Run build_features first.")

    settled = df[df["home_win"].notna()].sort_values("match_time").copy()
    splits = expanding_window_splits(settled, min_train_seasons=2)
    if not splits:
        raise RuntimeError("elo_tuner: not enough seasons for walk-forward validation.")

    if last_n_folds is not None:
        splits = splits[-last_n_folds:]

    logger.info(
        f"elo_tuner: grid search over {len(K_VALUES)}×{len(HA_VALUES)}×{len(REGRESSION_VALUES)} "
        f"= {len(K_VALUES)*len(HA_VALUES)*len(REGRESSION_VALUES)} combinations "
        f"across {len(splits)} folds."
    )

    grid = list(product(K_VALUES, HA_VALUES, REGRESSION_VALUES))
    results: list[tuple[float, float, float, float]] = []  # (brier, k, ha, reg)

    for k, ha, reg in grid:
        fold_briers: list[tuple[float, int]] = []  # (brier, n_settled)
        for train_df, test_df in splits:
            y_train = train_df["home_win"].astype(int)
            y_test = test_df["home_win"].astype(int)
            X_train = train_df.drop(columns=["home_win"])
            X_test = test_df.drop(columns=["home_win"])

            model = EloBaseline(k_factor=k, home_advantage=ha, season_regression=reg)
            model.fit(X_train, y_train)
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

        # Weighted mean Brier by fold size
        total_n = sum(n for _, n in fold_briers)
        wmean = sum(b * n for b, n in fold_briers) / total_n
        results.append((wmean, k, ha, reg))

    results.sort(key=lambda x: x[0])
    best_brier, best_k, best_ha, best_reg = results[0]

    logger.info(
        f"elo_tuner: best params — "
        f"K={best_k}, HA={best_ha}, regression={best_reg} "
        f"(brier={best_brier:.5f})"
    )

    # Log top 5
    logger.info("elo_tuner: top 5 combinations:")
    for brier, k, ha, reg in results[:5]:
        logger.info(f"  K={k:4.0f}  HA={ha:4.0f}  reg={reg:.2f}  → brier={brier:.5f}")

    best = {"k_factor": best_k, "home_advantage": best_ha, "season_regression": best_reg}
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(best, indent=2))
    logger.info(f"elo_tuner: saved best params to {OUTPUT_PATH}")
    return best


def _load_features() -> pd.DataFrame | None:
    files = sorted(FEATURES_DIR.glob("features*.parquet"), key=lambda p: p.stat().st_mtime)
    if not files:
        return None
    return pd.read_parquet(files[-1])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--folds", type=int, default=None, help="Limit to last N folds")
    args = parser.parse_args()
    run(last_n_folds=args.folds)
