"""
orchestration/jobs/train_models.py
------------------------------------
Job: Train baseline models on the feature DataFrame and save artifacts.

Uses a strict temporal split — the most recent season is held out for
validation. Training data is all prior seasons. This is a simple single-split
version of the full backtesting pipeline; for multi-fold evaluation run
`orchestration.jobs.run_backtest` instead.

Intended to run weekly (Monday morning) rather than daily.

Saves:
  - Model artifact (.pkl) to MODEL_ARTIFACTS_DIR
  - ModelRun record to the database with evaluation metrics

CLI usage:
    python -m orchestration.jobs.train_models
"""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from loguru import logger

from backtesting.calibration import calibration_bins, format_calibration_report
from backtesting.splits import expanding_window_splits
from config.settings import get_settings
from db.models.model_runs import ModelRun
from db.models.pipeline_runs import PipelineRun
from db.session import db_session
from evaluation.evaluator import Evaluator
from models.bookmaker_baseline import BookmakerBaseline
from models.elo_baseline import EloBaseline
from models.logistic_baseline import LogisticBaseline

settings = get_settings()
FEATURES_DIR = Path(settings.raw_snapshots_dir) / "features"
ARTIFACTS_DIR = Path(settings.model_artifacts_dir)


def run() -> None:
    """Train all baseline models using the latest temporal split and record results."""
    start = time.monotonic()
    logger.info("==> train_models: starting")
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

    df = _load_latest_features()
    if df is None or df.empty:
        logger.error("train_models: no feature data available. Run build_features first.")
        return

    if "home_win" not in df.columns:
        logger.error("train_models: target column 'home_win' not in features DataFrame.")
        return

    # Restrict to settled matches (have a result)
    settled = df[df["home_win"].notna()].sort_values("match_time", na_position="last").copy()
    if len(settled) < 30:
        logger.warning(
            f"train_models: only {len(settled)} settled matches — models will be unreliable."
        )

    # Use a single expanding-window fold: all-but-last-season as train,
    # last season as validation. This mirrors what the backtest runner does
    # for its final fold.
    splits = expanding_window_splits(settled, min_train_seasons=1)
    if not splits:
        logger.error(
            "train_models: not enough seasons for a temporal split. "
            "Need at least 2 seasons of settled data."
        )
        return

    # Use the last (most recent) split as the train/val pair
    X_train_full, X_val_full = splits[-1]
    val_season = sorted(X_val_full["season"].unique())
    logger.info(
        f"train_models: temporal split — "
        f"train={len(X_train_full)} rows, val={len(X_val_full)} rows (season={val_season})"
    )

    y_train = X_train_full["home_win"].astype(int)
    X_train = X_train_full.drop(columns=["home_win"])
    y_val = X_val_full["home_win"].astype(int)
    X_val = X_val_full.drop(columns=["home_win"])

    evaluator = Evaluator()
    models = [
        BookmakerBaseline(),
        EloBaseline(),
        LogisticBaseline(),
    ]

    with db_session() as db:
        pipeline_run = PipelineRun(job_name="train_models", status="running")
        db.add(pipeline_run)
        db.flush()

        for model in models:
            _train_and_record(db, model, X_train, y_train, X_val, y_val, evaluator)

        duration = time.monotonic() - start
        pipeline_run.status = "completed"
        pipeline_run.completed_at = datetime.now(tz=timezone.utc)
        pipeline_run.duration_seconds = round(duration, 2)
        pipeline_run.records_processed = len(models)

    logger.info(f"==> train_models: completed in {time.monotonic() - start:.1f}s")


def _train_and_record(
    db,
    model,
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_val: pd.DataFrame,
    y_val: pd.Series,
    evaluator: Evaluator,
) -> None:
    """Train a single model, evaluate it, and write a ModelRun record."""
    run_record = ModelRun(
        model_name=model.name,
        model_version=model.version,
        status="running",
    )
    db.add(run_record)
    db.flush()

    try:
        model.fit(X_train, y_train)
        preds = model.predict_proba(X_val)
        eval_result = evaluator.evaluate(model.name, preds, y_val)

        # Log calibration report
        settled_mask = y_val.notna()
        y_true_arr = y_val[settled_mask].values
        y_prob_arr = preds.loc[settled_mask, "home_win_prob"].values
        bins = calibration_bins(y_true_arr, y_prob_arr)
        logger.info(format_calibration_report(bins, model_name=model.name))

        artifact_path = None
        try:
            saved = model.save(ARTIFACTS_DIR)
            artifact_path = str(saved)
        except NotImplementedError:
            pass  # BookmakerBaseline has no artifact

        run_record.brier_score = eval_result.brier_score
        run_record.log_loss = eval_result.log_loss_score
        run_record.accuracy = eval_result.accuracy
        run_record.artifact_path = artifact_path
        run_record.metadata_json = json.dumps(model.metadata())
        run_record.status = "completed"
        run_record.completed_at = datetime.now(tz=timezone.utc)
        logger.info(
            f"train_models: {model.name} — "
            f"brier={eval_result.brier_score} "
            f"logloss={eval_result.log_loss_score} "
            f"acc={eval_result.accuracy}"
        )

    except Exception:
        run_record.status = "failed"
        run_record.error_message = "See logs"
        logger.exception(f"train_models: {model.name} FAILED")


def _load_latest_features() -> pd.DataFrame | None:
    """Load the most recently created features parquet file."""
    files = sorted(FEATURES_DIR.glob("features*.parquet"), key=lambda p: p.stat().st_mtime)
    if not files:
        return None
    path = files[-1]
    logger.info(f"train_models: loading features from {path}")
    return pd.read_parquet(path)


if __name__ == "__main__":
    try:
        run()
    except Exception:
        sys.exit(1)
