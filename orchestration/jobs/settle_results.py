"""
orchestration/jobs/settle_results.py
--------------------------------------
Job: Match settled AFL results against pending recommendations and record outcomes.

Run after matches complete on each match day (e.g. nightly after 23:00 AEST).
Updates Recommendation.status to 'settled' and creates BetOutcome records.
"""

import time
from datetime import datetime, timezone

from loguru import logger

from db.models.bet_outcomes import BetOutcome
from db.models.matches import Match
from db.models.pipeline_runs import PipelineRun
from db.models.predictions import Prediction
from db.models.recommendations import Recommendation
from db.session import db_session


def run() -> None:
    """Settle all pending recommendations where match results are available."""
    start = time.monotonic()
    logger.info("==> settle_results: starting")

    with db_session() as db:
        run_record = PipelineRun(job_name="settle_results", status="running")
        db.add(run_record)
        db.flush()

        try:
            settled_count = _settle_pending(db)

            duration = time.monotonic() - start
            run_record.status = "completed"
            run_record.completed_at = datetime.now(tz=timezone.utc)
            run_record.duration_seconds = round(duration, 2)
            run_record.records_processed = settled_count
            logger.info(f"==> settle_results: settled {settled_count} bets in {duration:.1f}s")

        except Exception as exc:
            run_record.status = "failed"
            run_record.error_message = str(exc)
            logger.exception("==> settle_results: FAILED")
            raise


def _settle_pending(db) -> int:
    """Find and settle all pending recommendations that now have a result."""
    pending = (
        db.query(Recommendation)
        .filter(Recommendation.status == "pending")
        .all()
    )

    settled = 0
    for rec in pending:
        # Walk: Recommendation → Prediction → Match
        prediction: Prediction | None = db.get(Prediction, rec.prediction_id)
        if prediction is None:
            continue
        match: Match | None = db.get(Match, prediction.match_id)
        if match is None or match.result is None:
            continue  # Not yet played

        won = _did_win(rec.side, match.result)
        profit_units = (
            rec.recommended_odds - 1.0 if won else -1.0
        )

        outcome = BetOutcome(
            recommendation_id=rec.id,
            won=won,
            profit_loss_units=round(profit_units, 6),
            profit_loss_dollars=(
                round(rec.stake_dollars * profit_units, 4) if rec.stake_dollars else None
            ),
            settled_at=datetime.now(tz=timezone.utc),
        )
        db.add(outcome)
        rec.status = "settled"
        settled += 1

    return settled


def _did_win(side: str, result: str) -> bool:
    """
    Determine if the recommended side won.

    Args:
        side: 'home' or 'away'
        result: 'home', 'away', or 'draw'

    Returns:
        True if the recommended side matches the result (draws never win).
    """
    return side == result


if __name__ == "__main__":
    run()
