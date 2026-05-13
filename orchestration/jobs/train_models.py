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

Hyperparameter loading:
  - If storage/model_artifacts/elo_best_params.json exists (from backtesting.elo_tuner),
    those params are used instead of EloBaseline defaults.
  - If storage/model_artifacts/xgb_best_params.json exists (from backtesting.xgb_tuner),
    those params are used instead of XGBoostModel defaults.

Calibration:
  - Logistic and XGBoost models are wrapped with post-hoc isotonic calibration.
  - The base model is trained on the penultimate fold's training set
    (seasons 1..N-2). The penultimate fold's test set (season N-1) is then
    used as the OOS calibration set. Evaluation happens on season N.
  - The base model is NOT refit on seasons 1..N-1 after calibration: an
    isotonic calibrator is tied to the output distribution of a specific
    base model. Refitting the base shifts that distribution, which leaves
    the calibrator pointing at stale probabilities (observed: ECE ballooned
    to 0.31 under the old flow). Cost: base sees one fewer season of
    training data. Benefit: probabilities are actually calibrated.

CLI usage:
    python -m orchestration.jobs.train_models
"""

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from loguru import logger

from backtesting.calibration import (
    calibration_bins,
    format_calibration_report,
)
from backtesting.splits import expanding_window_splits
from config.settings import get_settings
from db.models.model_runs import ModelRun
from db.models.pipeline_runs import PipelineRun
from db.session import db_session
from evaluation.evaluator import Evaluator
from models.bookmaker_baseline import BookmakerBaseline
from models.calibrated_model import CalibratedModel
from models.elo_baseline import EloBaseline
from models.logistic_baseline import LogisticBaseline
from models.poisson_model import PoissonModel
from models.xgboost_model import XGBoostModel

settings = get_settings()
FEATURES_DIR = Path(settings.raw_snapshots_dir) / "features"
ARTIFACTS_DIR = Path(settings.model_artifacts_dir)

_ELO_PARAMS_PATH = ARTIFACTS_DIR / "elo_best_params.json"
_XGB_PARAMS_PATH = ARTIFACTS_DIR / "xgb_best_params.json"


def _save_artifact_for_run(model, run_id: int, ts: datetime) -> Path | None:
    """Persist a trained model into a unique per-run subdirectory.

    Layout:
        ARTIFACTS_DIR / "run_<run_id>_<UTC_TIMESTAMP>" / <name>_<version>.pkl

    Each ModelRun gets its own immutable directory so later training runs
    cannot overwrite earlier artifacts. The filename inside the directory
    is unchanged — model.save() writes its usual <name>_<version>.pkl, and
    CalibratedModel writes the matching <name>_<version>_calibrator.pkl
    alongside it, so model.load(artifact_path.parent) still resolves both.

    Returns the artifact file path, or None for models that have no
    persistable artifact (BookmakerBaseline.save raises NotImplementedError).
    """
    ts_slug = ts.strftime("%Y%m%dT%H%M%SZ")
    per_run_dir = ARTIFACTS_DIR / f"run_{run_id}_{ts_slug}"
    per_run_dir.mkdir(parents=True, exist_ok=True)
    try:
        return Path(model.save(per_run_dir))
    except NotImplementedError:
        # Stateless model — remove the empty per-run dir we just created.
        try:
            per_run_dir.rmdir()
        except OSError:
            pass
        return None


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

    # Expanding-window splits:
    #   splits[-1]: train=all_but_last_season, val=last_season  (evaluation set)
    #   splits[-2]: train=all_but_last_two, cal=second_last     (calibration set)
    splits = expanding_window_splits(settled, min_train_seasons=1)
    if not splits:
        logger.error(
            "train_models: not enough seasons for a temporal split. "
            "Need at least 2 seasons of settled data."
        )
        return

    # Evaluation split: all-but-last as train, last as val
    X_train_full, X_val_full = splits[-1]
    val_season = sorted(X_val_full["season"].unique())

    # Calibration set: penultimate fold's test set (if available)
    X_cal_full: pd.DataFrame | None = None
    if len(splits) >= 2:
        _, X_cal_full = splits[-2]
        cal_season = sorted(X_cal_full["season"].unique())
        logger.info(
            f"train_models: temporal split — "
            f"train={len(X_train_full)} rows, val={len(X_val_full)} rows (season={val_season}), "
            f"cal={len(X_cal_full)} rows (season={cal_season})"
        )
    else:
        logger.info(
            f"train_models: temporal split — "
            f"train={len(X_train_full)} rows, val={len(X_val_full)} rows (season={val_season})"
        )

    y_train = X_train_full["home_win"].astype(int)
    # Keep home_score/away_score in X_train for PoissonModel score-mode;
    # all other models ignore unknown columns via their FEATURE_COLS filter.
    X_train = X_train_full.drop(columns=["home_win"])
    y_val = X_val_full["home_win"].astype(int)
    X_val = X_val_full.drop(columns=["home_win"])

    # Calibration split: train base on splits[-2].train (seasons 1..N-2),
    # fit isotonic calibrator on OOS predictions for splits[-2].test
    # (season N-1). The base model is deliberately NOT refit after
    # calibration — see module docstring. Evaluation happens on X_val
    # (season N), which the base has never seen.
    if len(splits) >= 2:
        X_cal_train_full, X_cal_test_full = splits[-2]
        X_cal = X_cal_test_full.drop(columns=["home_win"])
        y_cal = X_cal_test_full["home_win"].astype(int)
        X_cal_train = X_cal_train_full.drop(columns=["home_win"])
        y_cal_train = X_cal_train_full["home_win"].astype(int)
    else:
        X_cal = y_cal = X_cal_train = y_cal_train = None

    # Load tuned hyperparameters if available
    elo_params = _load_json_params(_ELO_PARAMS_PATH, "ELO")
    xgb_params = _load_json_params(_XGB_PARAMS_PATH, "XGBoost")

    evaluator = Evaluator()
    elo_model = EloBaseline(**elo_params) if elo_params else EloBaseline()
    xgb_base = XGBoostModel(**xgb_params) if xgb_params else XGBoostModel()

    # Wrap logistic and XGBoost with calibration
    logistic_cal = CalibratedModel(LogisticBaseline())
    xgboost_cal = CalibratedModel(xgb_base)

    models = [
        BookmakerBaseline(),
        elo_model,
        logistic_cal,
        xgboost_cal,
        PoissonModel(),
    ]

    with db_session() as db:
        pipeline_run = PipelineRun(job_name="train_models", status="running")
        db.add(pipeline_run)
        db.flush()

        for model in models:
            _train_and_record(
                db, model,
                X_train, y_train,
                X_val, y_val,
                evaluator,
                X_cal_train=X_cal_train, y_cal_train=y_cal_train,
                X_cal=X_cal, y_cal=y_cal,
            )

        duration = time.monotonic() - start
        pipeline_run.status = "completed"
        pipeline_run.completed_at = datetime.now(tz=UTC)
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
    X_cal_train: pd.DataFrame | None = None,
    y_cal_train: pd.Series | None = None,
    X_cal: pd.DataFrame | None = None,
    y_cal: pd.Series | None = None,
) -> None:
    """Train a single model, evaluate it, and write a ModelRun record.

    For CalibratedModel instances:
      1. Train base model on X_cal_train (penultimate fold's training set).
      2. Get out-of-sample preds on X_cal (penultimate fold's test set).
      3. Fit isotonic calibrator on those OOS predictions.
    The base model is NOT refit on X_train afterwards. Isotonic calibration
    is tied to a specific base model's output distribution; refitting the
    base invalidates the calibrator. See module docstring.
    """
    run_record = ModelRun(
        model_name=model.name,
        model_version=model.version,
        status="running",
    )
    db.add(run_record)
    db.flush()

    try:
        effective_train_frame = _actual_training_frame(model, X_train, X_cal_train)
        # For calibrated models: fit on the penultimate fold's train split,
        # then fit the isotonic calibrator on that fold's test split (OOS).
        # Do NOT refit the base — it would desync the calibrator.
        if (
            isinstance(model, CalibratedModel)
            and X_cal_train is not None
            and X_cal is not None
            and y_cal is not None
        ):
            model.fit(X_cal_train, y_cal_train)
            model.calibrate(X_cal, y_cal)
        else:
            model.fit(X_train, y_train)

        preds = model.predict_proba(X_val)
        eval_result = evaluator.evaluate(model.name, preds, y_val)

        # Log calibration report
        settled_mask = y_val.notna()
        y_true_arr = y_val[settled_mask].values
        y_prob_arr = preds.loc[settled_mask, "home_win_prob"].values
        bins = calibration_bins(y_true_arr, y_prob_arr)
        logger.info(format_calibration_report(bins, model_name=model.name))

        # Log XGBoost feature importances (3d)
        base = model._base if isinstance(model, CalibratedModel) else model
        if isinstance(base, XGBoostModel) and base._model is not None:
            _log_feature_importances(base)

        saved = _save_artifact_for_run(
            model, run_record.id, datetime.now(tz=UTC)
        )
        artifact_path = str(saved) if saved is not None else None

        run_record.brier_score = eval_result.brier_score
        run_record.log_loss = eval_result.log_loss_score
        run_record.accuracy = eval_result.accuracy
        run_record.artifact_path = artifact_path
        train_from, train_to = _season_range(effective_train_frame)
        run_record.train_from_season = train_from
        run_record.train_to_season = train_to
        run_record.metadata_json = json.dumps(
            _build_model_run_metadata(
                model,
                effective_train_frame,
                X_val,
                X_cal=X_cal,
            )
        )
        run_record.status = "completed"
        run_record.completed_at = datetime.now(tz=UTC)
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


def _actual_training_frame(
    model,
    X_train: pd.DataFrame,
    X_cal_train: pd.DataFrame | None,
) -> pd.DataFrame:
    """
    Return the frame that was actually used to fit the model.

    Calibrated models are intentionally fit on X_cal_train rather than X_train.
    """
    if isinstance(model, CalibratedModel) and X_cal_train is not None:
        return X_cal_train
    return X_train


def _season_range(df: pd.DataFrame | None) -> tuple[int | None, int | None]:
    """Return min/max season from a frame, or (None, None) if unavailable."""
    if df is None or df.empty or "season" not in df.columns:
        return None, None
    seasons = df["season"].dropna().astype(int)
    if seasons.empty:
        return None, None
    return int(seasons.min()), int(seasons.max())


def _feature_names_for_model(model) -> list[str]:
    """Extract the fitted feature list from the model when available."""
    base = model._base if isinstance(model, CalibratedModel) else model
    fit_features = getattr(base, "_fit_features", None)
    if fit_features:
        return [str(name) for name in fit_features]
    return []


def _build_model_run_metadata(
    model,
    effective_train_frame: pd.DataFrame,
    X_val: pd.DataFrame,
    X_cal: pd.DataFrame | None = None,
) -> dict:
    """Build stable provenance metadata for a completed ModelRun."""
    metadata = dict(model.metadata())
    feature_names = _feature_names_for_model(model)

    train_from, train_to = _season_range(effective_train_frame)
    val_from, val_to = _season_range(X_val)
    cal_from, cal_to = _season_range(X_cal)

    metadata.update(
        {
            "provenance_version": 1,
            "fitted_on_rows": len(effective_train_frame),
            "evaluated_on_rows": len(X_val),
            "calibrated_model": isinstance(model, CalibratedModel),
            "feature_names": feature_names,
            "n_features": len(feature_names),
            "train_from_season": train_from,
            "train_to_season": train_to,
            "evaluation_from_season": val_from,
            "evaluation_to_season": val_to,
            "calibration_from_season": cal_from,
            "calibration_to_season": cal_to,
            "calibration_rows": len(X_cal) if X_cal is not None else 0,
        }
    )
    return metadata


def _log_feature_importances(model: XGBoostModel) -> None:
    """Log XGBoost feature importances sorted by gain."""
    try:
        importances = model._model.feature_importances_
        features = model._fit_features
        pairs = sorted(zip(features, importances), key=lambda x: x[1], reverse=True)
        lines = ["XGBoost feature importances (gain, top 15):"]
        for feat, imp in pairs[:15]:
            bar = "#" * int(imp * 400)
            lines.append(f"  {feat:<35} {imp:.4f}  {bar}")
        logger.info("\n".join(lines))

        # Identify near-zero importance features
        low = [f for f, i in pairs if i < 0.005]
        if low:
            logger.info(f"XGBoost: low-importance features (< 0.005): {low}")
    except Exception as exc:
        logger.debug(f"Could not log feature importances: {exc}")


def _load_json_params(path: Path, label: str) -> dict | None:
    """Load hyperparameter JSON if it exists, else return None."""
    if path.exists():
        params = json.loads(path.read_text())
        logger.info(f"train_models: loaded {label} best params from {path}: {params}")
        return params
    logger.debug(f"train_models: no {label} params file at {path} — using defaults.")
    return None


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
