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

import time
from datetime import datetime, timezone

from loguru import logger

from config.settings import get_settings
from db.models.model_runs import ModelRun
from db.models.pipeline_runs import PipelineRun
from db.models.predictions import Prediction
from db.models.recommendations import Recommendation
from db.session import db_session
from features.feature_builder import FeatureBuilder
from models.bookmaker_baseline import BookmakerBaseline

settings = get_settings()


def run() -> None:
    """Generate and store recommendations for upcoming matches."""
    start = time.monotonic()
    logger.info("==> generate_recommendations: starting")

    with db_session() as db:
        run_record = PipelineRun(job_name="generate_recommendations", status="running")
        db.add(run_record)
        db.flush()

        try:
            # Load the best available model
            model, model_run = _load_best_model(db)
            if model_run is None:
                logger.warning("generate_recommendations: no trained model found. Exiting.")
                run_record.status = "completed"
                run_record.completed_at = datetime.now(tz=timezone.utc)
                return

            # Build features for upcoming (unsettled) matches only
            builder = FeatureBuilder(db)
            df = builder.build()
            upcoming = df[df["home_win"].isna()].copy()

            if upcoming.empty:
                logger.info("generate_recommendations: no upcoming matches with features.")
                run_record.status = "completed"
                run_record.completed_at = datetime.now(tz=timezone.utc)
                return

            # Predict
            preds_df = model.predict_proba(upcoming)
            recs_created = 0

            for _, pred_row in preds_df.iterrows():
                match_row = upcoming[upcoming["match_id"] == pred_row["match_id"]].iloc[0]
                recs_created += _create_prediction_and_rec(db, pred_row, match_row, model_run)

            duration = time.monotonic() - start
            run_record.status = "completed"
            run_record.completed_at = datetime.now(tz=timezone.utc)
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
    Load the latest completed model run.

    TODO: Select best model by lowest brier_score rather than most recent.
    """
    model_run = (
        db.query(ModelRun)
        .filter(ModelRun.status == "completed")
        .order_by(ModelRun.completed_at.desc())
        .first()
    )
    if model_run is None:
        return None, None

    # TODO: Load the correct model class based on model_run.model_name
    # For now, fall back to the bookmaker baseline (no artifact required)
    model = BookmakerBaseline()
    return model, model_run


def _create_prediction_and_rec(db, pred_row, match_row, model_run: ModelRun) -> int:
    """
    Store a Prediction and optionally a Recommendation for one match.

    Returns 1 if a recommendation was created, 0 otherwise.
    """
    home_prob = float(pred_row["home_win_prob"])
    away_prob = float(pred_row["away_win_prob"])
    match_id = int(pred_row["match_id"])

    # Compute edge vs. bookmaker implied probability
    bm_home = match_row.get("bm_home_implied_prob")
    bm_away = match_row.get("bm_away_implied_prob")
    home_edge = (home_prob - bm_home) if bm_home is not None else None
    away_edge = (away_prob - bm_away) if bm_away is not None else None

    # Kelly fraction: f = (bp - q) / b = edge / (odds - 1)
    home_odds = match_row.get("home_odds")
    away_odds = match_row.get("away_odds")
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

    # Create a recommendation if edge clears the threshold
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
