"""
orchestration/jobs/settle_results.py
--------------------------------------
Job: Match settled AFL results against pending recommendations and record outcomes.
Also computes Closing Line Value (CLV) where odds snapshot data is available.

Run after matches complete on each match day (e.g. nightly after 23:00 AEST).
Updates Recommendation.status to 'settled' and creates BetOutcome records.

CLV (Closing Line Value):
    CLV = 1/recommended_odds − 1/closing_odds  (per-unit edge vs closing market)
    Positive CLV → we had better implied probability than the closing line (value bet).
    Negative CLV → market moved against our pick before match start.
    Long-run positive CLV is the primary validation that the model finds real edge.
"""

import time
from datetime import datetime, timezone

from loguru import logger
from sqlalchemy import desc

from db.models.bet_outcomes import BetOutcome
from db.models.matches import Match
from db.models.odds_snapshots import OddsSnapshot
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
            _log_clv_summary(db)

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
        profit_units = rec.recommended_odds - 1.0 if won else -1.0

        # Compute CLV from the last odds snapshot before match time
        closing_odds, closing_implied_prob, clv = _compute_clv(
            db, match, rec.side, rec.recommended_odds
        )

        now = datetime.now(tz=timezone.utc)
        outcome = BetOutcome(
            recommendation_id=rec.id,
            bet_side=rec.side,
            bet_source="paper",
            recommended_odds=rec.recommended_odds,
            won=won,
            stake_fraction=rec.stake_fraction,
            stake_amount_aud=rec.stake_dollars,
            profit_loss_units=round(profit_units, 6),
            profit_loss_dollars=(
                round(rec.stake_dollars * profit_units, 4) if rec.stake_dollars else None
            ),
            closing_odds=closing_odds,
            closing_implied_prob=closing_implied_prob,
            clv=clv,
            clv_computed_at=now if clv is not None else None,
            settled_at=now,
        )
        db.add(outcome)
        rec.status = "settled"
        settled += 1

    return settled


def _compute_clv(db, match: Match, side: str, recommended_odds: float | None):
    """
    Find the last odds snapshot before match_time and compute CLV.

    CLV = (1/closing_odds) - (1/recommended_odds)
    Positive = we beat the closing line (bet at better odds than the close).
    Same sign convention as evaluation/clv_tracker.py.

    Returns:
        (closing_odds, closing_implied_prob, clv) — all None if no snapshot found.
    """
    if match.match_time is None or recommended_odds is None or recommended_odds <= 0:
        return None, None, None

    # Last snapshot strictly before match time
    snap: OddsSnapshot | None = (
        db.query(OddsSnapshot)
        .filter(
            OddsSnapshot.match_id == match.id,
            OddsSnapshot.snapshot_time < match.match_time,
        )
        .order_by(desc(OddsSnapshot.snapshot_time))
        .first()
    )

    if snap is None:
        return None, None, None

    closing_odds = snap.home_odds if side == "home" else snap.away_odds
    if closing_odds is None or closing_odds <= 0:
        return None, None, None

    closing_implied_prob = round(1.0 / closing_odds, 6)
    rec_implied_prob = 1.0 / recommended_odds
    clv = round(closing_implied_prob - rec_implied_prob, 6)

    return closing_odds, closing_implied_prob, clv


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


def _log_clv_summary(db) -> None:
    """Log a CLV summary across all settled paper bets with CLV data."""
    from sqlalchemy import func as sqlfunc
    rows = (
        db.query(BetOutcome)
        .filter(
            BetOutcome.bet_source == "paper",
            BetOutcome.clv.isnot(None),
        )
        .all()
    )
    if not rows:
        return

    clv_values = [r.clv for r in rows if r.clv is not None]
    n = len(clv_values)
    mean_clv = sum(clv_values) / n
    positive = sum(1 for c in clv_values if c > 0)
    total_units = sum(r.profit_loss_units for r in rows if r.profit_loss_units is not None)
    wins = sum(1 for r in rows if r.won)

    logger.info(
        f"CLV Summary: n={n} bets | mean_clv={mean_clv:+.4f} "
        f"| positive_clv={positive}/{n} ({100*positive/n:.0f}%) "
        f"| win_rate={wins}/{n} ({100*wins/n:.0f}%) "
        f"| total_pl_units={total_units:+.4f}"
    )


if __name__ == "__main__":
    run()
