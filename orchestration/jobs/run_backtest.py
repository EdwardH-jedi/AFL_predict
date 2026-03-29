"""
orchestration/jobs/run_backtest.py
------------------------------------
Job: Run the full walk-forward backtest for all baseline models.

Pipeline:
  1. Load the latest features parquet.
  2. Run expanding-window (or rolling-window) backtests.
  3. Compute per-fold and aggregate metrics.
  4. Save a JSON result artifact.
  5. Print a summary table.

All splits are strictly temporal — test data is always in the future relative
to all training data. See docs/backtesting.md for the full methodology.

CLI usage:
    python -m orchestration.jobs.run_backtest
    python -m orchestration.jobs.run_backtest --mode rolling --train-seasons 3
    python -m orchestration.jobs.run_backtest --min-train-seasons 2
    python -m orchestration.jobs.run_backtest --edge-threshold 0.05
"""

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from backtesting.runner import BacktestRunner
from config.settings import get_settings
from models.bookmaker_baseline import BookmakerBaseline
from models.elo_baseline import EloBaseline
from models.logistic_baseline import LogisticBaseline

settings = get_settings()
FEATURES_DIR = Path(settings.raw_snapshots_dir) / "features"
BACKTEST_DIR = Path(settings.raw_snapshots_dir) / "backtest_results"


def run(
    mode: str = "expanding",
    min_train_seasons: int = 2,
    edge_threshold: float = 0.03,
    max_kelly_fraction: float | None = None,
) -> None:
    """
    Run the full walk-forward backtest for all baseline models.

    Args:
        mode:               'expanding' or 'rolling'.
        min_train_seasons:  Minimum training seasons (expanding) or
                            training window size (rolling).
        edge_threshold:     Minimum model edge to recommend a bet.
        max_kelly_fraction: Kelly cap. Defaults to settings.max_kelly_fraction.
    """
    start = time.monotonic()
    logger.info(
        f"==> run_backtest: starting "
        f"(mode={mode}, min_train_seasons={min_train_seasons}, "
        f"edge_threshold={edge_threshold})"
    )

    if max_kelly_fraction is None:
        max_kelly_fraction = settings.max_kelly_fraction

    df = _load_latest_features()
    if df is None or df.empty:
        logger.error("run_backtest: no feature data. Run build_features first.")
        return

    models = [
        BookmakerBaseline(),
        EloBaseline(),
        LogisticBaseline(),
    ]

    runner = BacktestRunner(
        mode=mode,
        min_train_seasons=min_train_seasons,
        edge_threshold=edge_threshold,
        max_kelly_fraction=max_kelly_fraction,
    )

    result = runner.run(df, models)

    # Save artifact
    path = result.save(BACKTEST_DIR)

    duration = time.monotonic() - start
    logger.info(f"==> run_backtest: completed in {duration:.1f}s — results at {path}")

    # Print summary table to stdout as well
    agg = result.aggregate_df()
    if not agg.empty:
        _key_cols = [
            "model_name", "n_folds", "n_settled_total",
            "brier_score", "log_loss", "accuracy", "ece",
            "n_bets_total", "hit_rate", "avg_edge", "roi",
        ]
        display_cols = [c for c in _key_cols if c in agg.columns]
        print("\n" + agg[display_cols].to_string(index=False))


def _load_latest_features():
    """Load the most recently written features parquet file."""
    import pandas as pd
    files = sorted(FEATURES_DIR.glob("features*.parquet"), key=lambda p: p.stat().st_mtime)
    if not files:
        logger.error(f"run_backtest: no parquet files found in {FEATURES_DIR}")
        return None
    path = files[-1]
    logger.info(f"run_backtest: loading features from {path}")
    df = pd.read_parquet(path)
    logger.info(f"run_backtest: loaded {len(df)} rows × {len(df.columns)} columns")
    return df


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Walk-forward backtest for AFL prediction baseline models."
    )
    p.add_argument(
        "--mode", choices=["expanding", "rolling"], default="expanding",
        help="Split mode: expanding (all-history) or rolling (fixed window). Default: expanding."
    )
    p.add_argument(
        "--min-train-seasons", type=int, default=2,
        dest="min_train_seasons",
        help="Minimum training seasons (expanding) or window size (rolling). Default: 2."
    )
    p.add_argument(
        "--edge-threshold", type=float, default=0.03,
        dest="edge_threshold",
        help="Minimum edge (model_prob - bm_implied_prob) to recommend a bet. Default: 0.03."
    )
    p.add_argument(
        "--max-kelly", type=float, default=None,
        dest="max_kelly_fraction",
        help="Kelly fraction cap. Defaults to settings.max_kelly_fraction (0.05)."
    )
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    try:
        run(
            mode=args.mode,
            min_train_seasons=args.min_train_seasons,
            edge_threshold=args.edge_threshold,
            max_kelly_fraction=args.max_kelly_fraction,
        )
    except Exception:
        logger.exception("run_backtest: unhandled error")
        sys.exit(1)
