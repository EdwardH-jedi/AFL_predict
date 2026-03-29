"""
orchestration/jobs/generate_daily_summary.py
----------------------------------------------
Job: Write a daily summary JSON artifact to storage/daily_summaries/.

The artifact is a human-readable snapshot of the day's pipeline run,
recommendations, bankroll state, and freshness warnings.  It is the
primary artefact reviewed on the main computer and MacBook each morning.

Filename pattern: YYYY-MM-DD.json (UTC date of the pipeline run).
Existing files for the same date are overwritten.

This is a SOFT job — failure is logged but does not stop the pipeline.
"""

import json
import os
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

from config.settings import get_settings
from db.models.bankroll_logs import BankrollLog
from db.models.bet_outcomes import BetOutcome
from db.models.daily_pipeline_runs import DailyPipelineRun
from db.models.matches import Match
from db.models.pipeline_runs import PipelineRun
from db.models.predictions import Prediction
from db.models.recommendations import Recommendation
from db.session import db_session
from orchestration.jobs.check_data_freshness import get_last_result as get_freshness

settings = get_settings()

# Injected by the orchestrator before this job runs.
# Holds the id of the current DailyPipelineRun so we can query it.
_current_daily_run_id: int | None = None


def set_daily_run_id(run_id: int) -> None:
    global _current_daily_run_id
    _current_daily_run_id = run_id


def run() -> None:
    """Write today's summary artifact."""
    start = time.monotonic()
    today = date.today().isoformat()
    logger.info(f"==> generate_daily_summary: building summary for {today}")

    summary = _build_summary()

    output_dir = Path(settings.daily_summary_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{today}.json"

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)

    duration = time.monotonic() - start
    logger.info(
        f"==> generate_daily_summary: wrote {output_path} in {duration:.1f}s"
    )


# ---------------------------------------------------------------------------
# Internal builders
# ---------------------------------------------------------------------------

def _build_summary() -> dict[str, Any]:
    now = datetime.now(tz=timezone.utc)
    today = date.today()

    with db_session() as db:
        pipeline_section = _pipeline_status(db, today)
        recs_section = _latest_recommendations(db, limit=10)
        bankroll_section = _bankroll_snapshot(db)
        outcomes_section = _recent_outcomes(db, limit=20)
        no_bet_section = _no_bet_analysis(recs_section)

    freshness = get_freshness() or {}

    return {
        "date": today.isoformat(),
        "generated_at": now.isoformat(),
        "pipeline": pipeline_section,
        "freshness": freshness,
        "recommendations": recs_section,
        "bankroll": bankroll_section,
        "recent_outcomes": outcomes_section,
        "no_bet_day": no_bet_section,
    }


def _pipeline_status(db, today: date) -> dict[str, Any]:
    """Summarise today's DailyPipelineRun and its child jobs."""
    daily_run: DailyPipelineRun | None = None
    if _current_daily_run_id:
        daily_run = db.get(DailyPipelineRun, _current_daily_run_id)

    if daily_run is None:
        # Fallback: latest run for today
        daily_run = (
            db.query(DailyPipelineRun)
            .filter(DailyPipelineRun.run_date == today)
            .order_by(DailyPipelineRun.id.desc())
            .first()
        )

    if daily_run is None:
        return {"status": "unknown", "jobs": []}

    jobs = (
        db.query(PipelineRun)
        .filter(PipelineRun.daily_run_id == daily_run.id)
        .order_by(PipelineRun.id)
        .all()
    )

    return {
        "status": daily_run.status,
        "run_uuid": daily_run.run_uuid,
        "triggered_by": daily_run.triggered_by,
        "started_at": daily_run.started_at.isoformat() if daily_run.started_at else None,
        "completed_at": daily_run.completed_at.isoformat() if daily_run.completed_at else None,
        "duration_seconds": daily_run.duration_seconds,
        "jobs": [
            {
                "name": j.job_name,
                "status": j.status,
                "duration_seconds": j.duration_seconds,
                "retry_count": j.retry_count,
                "records_processed": j.records_processed,
                "error": j.error_message,
            }
            for j in jobs
        ],
    }


def _latest_recommendations(db, limit: int = 10) -> list[dict[str, Any]]:
    """Return most recent recommendations with match context."""
    recs = (
        db.query(Recommendation)
        .order_by(Recommendation.created_at.desc())
        .limit(limit)
        .all()
    )
    result = []
    for rec in recs:
        pred: Prediction | None = db.get(Prediction, rec.prediction_id)
        match: Match | None = db.get(Match, pred.match_id) if pred else None
        result.append({
            "rec_id": rec.id,
            "match_id": pred.match_id if pred else None,
            "home_team": match.home_team_id if match else None,
            "away_team": match.away_team_id if match else None,
            "match_date": match.match_time.isoformat() if match and match.match_time else None,
            "side": rec.side,
            "odds": rec.recommended_odds,
            "stake_fraction": rec.stake_fraction,
            "status": rec.status,
            "paper_trade": rec.paper_trade,
            "created_at": rec.created_at.isoformat(),
        })
    return result


def _bankroll_snapshot(db) -> dict[str, Any]:
    """Return current bankroll and basic drawdown stats."""
    logs = (
        db.query(BankrollLog)
        .order_by(BankrollLog.created_at.asc())
        .all()
    )
    if not logs:
        return {"current_balance": None, "peak_balance": None, "drawdown": None, "n_events": 0}

    balances = [l.balance_after for l in logs]
    current = balances[-1]
    peak = max(balances)
    drawdown = round((peak - current) / peak, 6) if peak > 0 else 0.0

    return {
        "current_balance": round(current, 4),
        "peak_balance": round(peak, 4),
        "drawdown": drawdown,
        "n_events": len(logs),
        "last_event": logs[-1].event_type,
        "last_event_at": logs[-1].created_at.isoformat(),
    }


def _recent_outcomes(db, limit: int = 20) -> list[dict[str, Any]]:
    """Return recent settled bet outcomes."""
    outcomes = (
        db.query(BetOutcome)
        .order_by(BetOutcome.settled_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "recommendation_id": o.recommendation_id,
            "won": o.won,
            "profit_loss_units": o.profit_loss_units,
            "profit_loss_dollars": o.profit_loss_dollars,
            "settled_at": o.settled_at.isoformat() if o.settled_at else None,
        }
        for o in outcomes
    ]


def _no_bet_analysis(recs: list[dict]) -> dict[str, Any]:
    """Determine if today is a no-bet day and why."""
    today = date.today().isoformat()
    today_recs = [r for r in recs if r.get("created_at", "").startswith(today)]
    if today_recs:
        return {"is_no_bet_day": False, "reason": None, "today_rec_count": len(today_recs)}
    return {
        "is_no_bet_day": True,
        "reason": "No recommendations generated today (edge below threshold or no upcoming matches).",
        "today_rec_count": 0,
    }


if __name__ == "__main__":
    run()
