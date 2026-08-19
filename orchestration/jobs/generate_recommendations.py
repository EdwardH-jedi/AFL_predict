"""
orchestration/jobs/generate_recommendations.py
------------------------------------------------
Job: Generate paper-trade betting recommendations for upcoming matches.

Uses the latest trained model (by default the best-performing on validation)
to predict win probabilities, computes edge vs. bookmaker, and emits
recommendations for matches where edge > settings.min_edge_threshold.

ALL recommendations are paper_trade=True in this MVP.
Run daily at ~08:00 AEST after odds ingestion.
"""

import json
import time
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from loguru import logger

from config.settings import get_settings
from db.models.bet_outcomes import BetOutcome
from db.models.model_runs import ModelRun
from db.models.pipeline_runs import PipelineRun
from db.models.predictions import Prediction
from db.models.recommendations import Recommendation
from db.session import db_session
from features.feature_builder import FeatureBuilder
from models.base_model import BaseModel
from models.bookmaker_baseline import BookmakerBaseline
from models.calibrated_model import CalibratedModel
from models.elo_baseline import EloBaseline
from models.ensemble import Ensemble
from models.logistic_baseline import LogisticBaseline
from models.poisson_model import PoissonModel
from models.xgboost_model import XGBoostModel

# Models whose artifacts are wrapped in CalibratedModel after loading.
_CALIBRATED_MODELS = {"logistic_baseline", "xgboost"}

settings = get_settings()

# Maps model_run.model_name to model class.
_MODEL_REGISTRY: dict[str, type[BaseModel]] = {
    "bookmaker_baseline": BookmakerBaseline,
    "bookmaker": BookmakerBaseline,
    "elo_baseline": EloBaseline,
    "elo": EloBaseline,
    "logistic_baseline": LogisticBaseline,
    "logistic": LogisticBaseline,
    "xgboost_model": XGBoostModel,
    "xgboost": XGBoostModel,
    "poisson_model": PoissonModel,
    "poisson": PoissonModel,
}

# Models that work without a saved artifact (stateless at inference time).
# Must include every registered name variant (see _MODEL_REGISTRY above) — the
# actual model_name strings persisted to ModelRun are the long forms, e.g.
# 'bookmaker_baseline' / 'elo_baseline' (set by BaseModel.name on each class).
_STATELESS_MODELS = {"bookmaker", "bookmaker_baseline", "elo", "elo_baseline"}

# Ensemble component weights come from config.settings — see
# Settings.ensemble_weights, which is the single source of truth for the
# production blend. Do NOT reintroduce a module-level weight table here: the
# dashboard API reads the same property, and two tables drift apart silently.


def run() -> None:
    """Generate and store recommendations for upcoming matches."""
    start = time.monotonic()
    logger.info("==> generate_recommendations: starting")

    with db_session() as db:
        run_record = PipelineRun(job_name="generate_recommendations", status="running")
        db.add(run_record)
        db.flush()

        try:
            model, model_run = _load_best_model(db)
            if model_run is None:
                logger.warning("generate_recommendations: no trained model found. Exiting.")
                run_record.status = "completed"
                run_record.completed_at = datetime.now(tz=UTC)
                return

            now = datetime.now(tz=UTC)
            builder = FeatureBuilder(db)
            df = builder.build()
            upcoming = df[
                df["home_win"].isna()
                & (pd.to_datetime(df["match_time"], utc=True) > now)
            ].copy()

            if upcoming.empty:
                logger.info("generate_recommendations: no upcoming matches with features.")
                run_record.status = "completed"
                run_record.completed_at = datetime.now(tz=UTC)
                return

            upcoming_match_ids = [int(mid) for mid in upcoming["match_id"].dropna().unique()]
            # Void only pending recs that have NOT been placed/tracked. Any rec
            # with a BetOutcome row (paper-settled or manually recorded via
            # tab_tracking) is preserved so settle_results / performance history
            # can still resolve it.
            voided = (
                db.query(Recommendation)
                .join(Prediction, Recommendation.prediction_id == Prediction.id)
                .outerjoin(BetOutcome, BetOutcome.recommendation_id == Recommendation.id)
                .filter(
                    Prediction.match_id.in_(upcoming_match_ids),
                    Recommendation.status == "pending",
                    BetOutcome.id.is_(None),
                )
                .all()
            )
            for old_rec in voided:
                old_rec.status = "void"
            if voided:
                logger.info(
                    f"generate_recommendations: voided {len(voided)} stale pending "
                    "recommendation(s) without bet outcomes before regenerating."
                )

            preds_df = model.predict_proba(upcoming)
            recs_created = 0

            for _, pred_row in preds_df.iterrows():
                match_row = upcoming[upcoming["match_id"] == pred_row["match_id"]].iloc[0]
                recs_created += _create_prediction_and_rec(db, pred_row, match_row, model_run)

            duration = time.monotonic() - start
            run_record.status = "completed"
            run_record.completed_at = datetime.now(tz=UTC)
            run_record.duration_seconds = round(duration, 2)
            run_record.records_processed = recs_created
            logger.info(
                f"==> generate_recommendations: {recs_created} recommendations "
                f"created in {duration:.1f}s"
            )

        except Exception as exc:
            run_record.status = "failed"
            run_record.error_message = str(exc)
            logger.exception("==> generate_recommendations: FAILED")
            raise


def _load_best_model(db):
    """
    Try to build a weighted ensemble from the best available trained models.
    Falls back to the single best model (lowest Brier) if ensemble cannot be built.

    Returns (model, reference_model_run).
    The reference_model_run is the model run used for DB bookkeeping in
    Prediction records.
    """
    ensemble_model, ref_run = _try_build_ensemble(db)
    if ensemble_model is not None:
        return ensemble_model, ref_run

    model_run = _select_single_model_run(
        db,
        with_brier=True,
        order_by=ModelRun.brier_score.asc(),
    )
    if model_run is None:
        model_run = _select_single_model_run(
            db,
            with_brier=False,
            order_by=ModelRun.completed_at.desc(),
        )
    if model_run is None:
        return None, None

    logger.info(
        f"_load_best_model: single model {model_run.model_name!r} "
        f"(brier={model_run.brier_score}, run_id={model_run.id})"
    )
    return _instantiate_model(model_run), model_run


def _try_build_ensemble(db):
    """
    Attempt to construct a weighted Ensemble from the best run of each component.

    Returns (Ensemble, ref_model_run) if at least two compatible components
    are loadable, otherwise (None, None).
    """
    components: list[tuple[BaseModel, float]] = []
    ref_run = None
    first_loaded_run = None

    weights = settings.ensemble_weights
    if not weights:
        logger.warning(
            "_try_build_ensemble: no positive ensemble weights configured "
            "(check ENSEMBLE_WEIGHT_* in .env) -- falling back to single best model."
        )
        return None, None

    for model_name, weight in weights.items():
        candidates = (
            db.query(ModelRun)
            .filter(
                ModelRun.status == "completed",
                ModelRun.model_name == model_name,
                ModelRun.brier_score.isnot(None),
            )
            .order_by(ModelRun.brier_score.asc())
            .limit(20)
            .all()
        )

        run = None
        for candidate in candidates:
            if not _is_model_run_schema_compatible(candidate):
                continue
            run = candidate
            break

        if run is None:
            logger.debug(f"_try_build_ensemble: no compatible run for {model_name!r} -- skipping")
            continue

        model = _instantiate_model(run)
        if isinstance(model, BookmakerBaseline) and model_name != "bookmaker_baseline":
            logger.debug(f"_try_build_ensemble: {model_name!r} artifact unavailable -- skipping")
            continue

        components.append((model, weight))
        if first_loaded_run is None:
            first_loaded_run = run
        logger.info(
            f"_try_build_ensemble: loaded {model_name!r} "
            f"(brier={run.brier_score}, run_id={run.id}, weight={weight})"
        )
        if model_name in ("logistic_baseline", "xgboost"):
            if ref_run is None or model_name == "xgboost":
                ref_run = run

    if len(components) < 2:
        logger.info(
            "_try_build_ensemble: fewer than 2 components available -- "
            "falling back to single best model."
        )
        return None, None

    ref_run = ref_run or first_loaded_run
    ensemble = Ensemble(components)
    active = [m.name for m, _ in components]
    logger.info(f"_load_best_model: ensemble built from {active} (ref run_id={ref_run.id})")
    return ensemble, ref_run


def _select_single_model_run(db, with_brier: bool, order_by):
    """Return the best compatible ModelRun for single-model fallback."""
    query = db.query(ModelRun).filter(ModelRun.status == "completed")
    if with_brier:
        query = query.filter(ModelRun.brier_score.isnot(None))

    for candidate in query.order_by(order_by).limit(50).all():
        if not _is_model_run_schema_compatible(candidate):
            continue
        model = _instantiate_model(candidate)
        if isinstance(model, BookmakerBaseline) and candidate.model_name != "bookmaker_baseline":
            logger.debug(
                f"_select_single_model_run: skipping run_id={candidate.id} "
                f"({candidate.model_name}) because artifact load fell back to bookmaker baseline"
            )
            continue
        return candidate
    return None


def _expected_n_features_by_model() -> dict[str, int]:
    from models.logistic_baseline import FEATURE_COLS as logistic_feature_cols
    from models.xgboost_model import FEATURE_COLS as xgb_feature_cols

    return {
        "logistic_baseline": len(logistic_feature_cols),
        "xgboost": len(xgb_feature_cols),
    }


def _parse_model_metadata(model_run: ModelRun) -> dict:
    if not model_run.metadata_json:
        return {}
    try:
        parsed = json.loads(model_run.metadata_json)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _is_model_run_schema_compatible(model_run: ModelRun) -> bool:
    """Check whether a stored ModelRun matches the current feature schema."""
    expected_n = _expected_n_features_by_model().get(model_run.model_name)
    if expected_n is None:
        return True

    stored_n = _parse_model_metadata(model_run).get("n_features")
    if stored_n == expected_n:
        return True

    logger.debug(
        f"_is_model_run_schema_compatible: skipping run_id={model_run.id} "
        f"({model_run.model_name}) because n_features={stored_n!r} != expected {expected_n}"
    )
    return False


def _instantiate_model(model_run: ModelRun) -> BaseModel:
    """
    Instantiate and, if applicable, load the model corresponding to model_run.

    Priority:
      1. Known class + artifact on disk  -> load from artifact
      2. Stateless known class           -> return fresh instance
      3. Anything else                   -> warn and return BookmakerBaseline
    """
    cls = _MODEL_REGISTRY.get(model_run.model_name)
    if cls is None:
        logger.warning(
            f"Unknown model_name {model_run.model_name!r}. "
            "Falling back to BookmakerBaseline."
        )
        return BookmakerBaseline()

    model: BaseModel = cls()

    if model_run.artifact_path:
        artifact_path = Path(model_run.artifact_path)
        if artifact_path.exists():
            try:
                if model_run.model_name in _CALIBRATED_MODELS:
                    cal_model = CalibratedModel(model)
                    cal_model.load(artifact_path.parent)
                    logger.info(
                        f"Loaded {model_run.model_name!r} (calibrated) from {artifact_path}"
                    )
                    return cal_model
                model.load(artifact_path.parent)
                logger.info(f"Loaded {model_run.model_name!r} artifact from {artifact_path}")
                return model
            except Exception as exc:
                logger.warning(
                    f"Failed to load artifact {artifact_path}: {exc}. "
                    "Falling back to BookmakerBaseline."
                )
                return BookmakerBaseline()
        logger.warning(
            f"Artifact path {artifact_path} not found on disk. "
            "Falling back to BookmakerBaseline."
        )
        return BookmakerBaseline()

    if model_run.model_name in _STATELESS_MODELS:
        logger.info(f"Using stateless model {model_run.model_name!r} (no artifact required).")
        return model

    logger.warning(
        f"No artifact_path for fitted model {model_run.model_name!r}. "
        "Falling back to BookmakerBaseline."
    )
    return BookmakerBaseline()


def _create_prediction_and_rec(db, pred_row, match_row, model_run: ModelRun) -> int:
    """
    Store a Prediction and optionally a Recommendation for one match.

    Returns 1 if a recommendation was created, 0 otherwise.
    """
    home_prob = float(pred_row["home_win_prob"])
    away_prob = float(pred_row["away_win_prob"])
    match_id = int(pred_row["match_id"])

    bm_home = match_row.get("bm_home_implied_prob")
    bm_away = match_row.get("bm_away_implied_prob")
    home_edge = (home_prob - bm_home) if bm_home is not None else None
    away_edge = (away_prob - bm_away) if bm_away is not None else None

    home_odds = match_row.get("bm_home_odds")
    away_odds = match_row.get("bm_away_odds")
    kelly_home = _kelly(home_prob, home_odds) if home_odds else None
    kelly_away = _kelly(away_prob, away_odds) if away_odds else None

    prediction = Prediction(
        match_id=match_id,
        model_run_id=model_run.id,
        home_win_prob=home_prob,
        away_win_prob=away_prob,
        home_edge=home_edge,
        away_edge=away_edge,
        kelly_home=kelly_home,
        kelly_away=kelly_away,
    )
    db.add(prediction)
    db.flush()

    rec_created = 0
    if home_edge is not None and home_edge >= settings.min_edge_threshold and home_odds:
        rec = Recommendation(
            prediction_id=prediction.id,
            side="home",
            recommended_odds=home_odds,
            stake_fraction=min(kelly_home or 0.0, settings.max_kelly_fraction),
            paper_trade=True,
            status="pending",
        )
        db.add(rec)
        rec_created = 1
    elif away_edge is not None and away_edge >= settings.min_edge_threshold and away_odds:
        rec = Recommendation(
            prediction_id=prediction.id,
            side="away",
            recommended_odds=away_odds,
            stake_fraction=min(kelly_away or 0.0, settings.max_kelly_fraction),
            paper_trade=True,
            status="pending",
        )
        db.add(rec)
        rec_created = 1

    return rec_created


def _kelly(win_prob: float, decimal_odds: float) -> float:
    """
    Full Kelly fraction. Always cap at settings.max_kelly_fraction.
    f = (b*p - q) / b where b = decimal_odds - 1, q = 1 - p
    """
    b = decimal_odds - 1.0
    if b <= 0:
        return 0.0
    f = (b * win_prob - (1.0 - win_prob)) / b
    return max(0.0, min(f, settings.max_kelly_fraction))


if __name__ == "__main__":
    run()
