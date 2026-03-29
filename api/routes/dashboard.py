"""
api/routes/dashboard.py
------------------------
Lightweight dashboard / reporting API.

All endpoints are read-only GET.  No state is mutated here.
Designed for quick human review on the main computer or MacBook.

Endpoints:
  GET /dashboard/summary       — combined daily summary
  GET /dashboard/pipeline      — recent pipeline run history
  GET /dashboard/bankroll      — bankroll trend (time series)
  GET /dashboard/recommendations — recent recommendations with outcomes
  GET /dashboard/freshness     — latest data freshness status
  GET /dashboard/no-bet-days   — days with no recommendations in last 30d
  GET /dashboard/readiness     — live-readiness report
"""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from config.settings import get_settings
from db.models.bankroll_logs import BankrollLog
from db.models.bet_outcomes import BetOutcome
from db.models.daily_pipeline_runs import DailyPipelineRun
from db.models.matches import Match
from db.models.pipeline_runs import PipelineRun
from db.models.predictions import Prediction
from db.models.recommendations import Recommendation
from db.session import get_db
from evaluation.live_readiness import evaluate as evaluate_readiness

settings = get_settings()
router = APIRouter()


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

@router.get("/summary")
def get_summary(db: Session = Depends(get_db)) -> dict[str, Any]:
    """
    Combined daily summary.

    Returns pipeline status, bankroll snapshot, today's recommendations,
    recent outcomes, and freshness warnings from the latest daily artifact.
    """
    today = date.today()

    # Try to load from artifact first (faster than DB queries)
    artifact = _load_latest_artifact()
    if artifact:
        return {"source": "artifact", "data": artifact}

    # Fallback: build from DB live
    return {
        "source": "live",
        "data": {
            "date": today.isoformat(),
            "pipeline": _pipeline_latest(db, today),
            "bankroll": _bankroll_snapshot(db),
            "recommendations": _recent_recommendations(db, limit=5),
            "freshness_warnings": _freshness_warnings(db),
        },
    }


# ---------------------------------------------------------------------------
# Pipeline history
# ---------------------------------------------------------------------------

@router.get("/pipeline")
def get_pipeline_history(days: int = 14, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Recent pipeline run history (default last 14 days)."""
    days = min(max(days, 1), 90)  # clamp 1–90
    cutoff = date.today() - timedelta(days=days)

    runs = (
        db.query(DailyPipelineRun)
        .filter(DailyPipelineRun.run_date >= cutoff)
        .order_by(DailyPipelineRun.run_date.desc())
        .all()
    )

    result = []
    for run in runs:
        jobs = (
            db.query(PipelineRun)
            .filter(PipelineRun.daily_run_id == run.id)
            .order_by(PipelineRun.id)
            .all()
        )
        result.append({
            "id": run.id,
            "date": run.run_date.isoformat(),
            "status": run.status,
            "triggered_by": run.triggered_by,
            "duration_seconds": run.duration_seconds,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "jobs": [
                {
                    "name": j.job_name,
                    "status": j.status,
                    "duration_seconds": j.duration_seconds,
                    "retry_count": j.retry_count,
                    "error": j.error_message,
                }
                for j in jobs
            ],
        })

    return {"days_requested": days, "runs": result}


# ---------------------------------------------------------------------------
# Bankroll trend
# ---------------------------------------------------------------------------

@router.get("/bankroll")
def get_bankroll_trend(days: int = 60, db: Session = Depends(get_db)) -> dict[str, Any]:
    """
    Bankroll balance time series for the last N days.

    Returns data suitable for a simple line chart.
    """
    days = min(max(days, 7), 365)
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days)

    logs = (
        db.query(BankrollLog)
        .filter(BankrollLog.created_at >= cutoff)
        .order_by(BankrollLog.created_at.asc())
        .all()
    )

    if not logs:
        return {"days": days, "series": [], "current": None, "drawdown": None}

    series = [
        {
            "at": l.created_at.isoformat(),
            "balance": round(l.balance_after, 4),
            "event": l.event_type,
        }
        for l in logs
    ]

    balances = [l.balance_after for l in logs]
    peak = max(balances)
    current = balances[-1]
    drawdown = round((peak - current) / peak, 6) if peak > 0 else 0.0

    return {
        "days": days,
        "current": round(current, 4),
        "peak": round(peak, 4),
        "drawdown": drawdown,
        "series": series,
    }


# ---------------------------------------------------------------------------
# Recommendations
# ---------------------------------------------------------------------------

@router.get("/recommendations")
def get_recommendations(limit: int = 20, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Recent recommendations with outcomes where available."""
    limit = min(max(limit, 1), 100)

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
        outcome: Any = rec.bet_outcome  # relationship

        result.append({
            "id": rec.id,
            "match_id": pred.match_id if pred else None,
            "home_team": match.home_team_id if match else None,
            "away_team": match.away_team_id if match else None,
            "match_date": match.match_time.isoformat() if match and match.match_time else None,
            "side": rec.side,
            "odds": rec.recommended_odds,
            "stake_fraction": rec.stake_fraction,
            "stake_dollars": rec.stake_dollars,
            "status": rec.status,
            "paper_trade": rec.paper_trade,
            "created_at": rec.created_at.isoformat(),
            "outcome": {
                "won": outcome.won,
                "pl_units": outcome.profit_loss_units,
                "pl_dollars": outcome.profit_loss_dollars,
                "settled_at": outcome.settled_at.isoformat() if outcome.settled_at else None,
            } if outcome else None,
        })

    return {"limit": limit, "count": len(result), "recommendations": result}


# ---------------------------------------------------------------------------
# Data freshness
# ---------------------------------------------------------------------------

@router.get("/freshness")
def get_freshness(db: Session = Depends(get_db)) -> dict[str, Any]:
    """
    Data freshness status: age of most recent odds and fixture snapshots.
    """
    from db.models.odds_snapshots import OddsSnapshot
    from db.models.matches import Match

    now = datetime.now(tz=timezone.utc)
    warnings: list[str] = []

    latest_odds: OddsSnapshot | None = (
        db.query(OddsSnapshot).order_by(OddsSnapshot.snapshot_time.desc()).first()
    )
    latest_match: Match | None = (
        db.query(Match).order_by(Match.updated_at.desc()).first()
    )

    def age_hours(dt: datetime | None) -> float | None:
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return round((now - dt).total_seconds() / 3600, 2)

    odds_age = age_hours(latest_odds.snapshot_time if latest_odds else None)
    afl_age = age_hours(latest_match.updated_at if latest_match else None)

    if odds_age is None or odds_age > settings.odds_freshness_hours:
        warnings.append(
            f"Odds stale: {odds_age}h (threshold {settings.odds_freshness_hours}h)"
            if odds_age else "No odds data."
        )
    if afl_age is None or afl_age > settings.afl_freshness_hours:
        warnings.append(
            f"AFL fixtures stale: {afl_age}h (threshold {settings.afl_freshness_hours}h)"
            if afl_age else "No AFL fixture data."
        )

    return {
        "checked_at": now.isoformat(),
        "odds_age_hours": odds_age,
        "odds_stale": odds_age is None or odds_age > settings.odds_freshness_hours,
        "afl_age_hours": afl_age,
        "afl_stale": afl_age is None or afl_age > settings.afl_freshness_hours,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# No-bet days
# ---------------------------------------------------------------------------

@router.get("/no-bet-days")
def get_no_bet_days(days: int = 30, db: Session = Depends(get_db)) -> dict[str, Any]:
    """
    Days in the last N days where no recommendations were generated.

    A no-bet day is expected when there are no upcoming matches, or when
    no match clears the edge threshold.
    """
    days = min(max(days, 7), 90)
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days)

    recs = (
        db.query(Recommendation)
        .filter(Recommendation.created_at >= cutoff)
        .order_by(Recommendation.created_at.asc())
        .all()
    )

    bet_days: set[str] = {r.created_at.date().isoformat() for r in recs}

    # Days covered by pipeline runs in this window
    pipeline_dates = {
        str(r.run_date)
        for r in db.query(DailyPipelineRun)
        .filter(DailyPipelineRun.run_date >= cutoff.date())
        .all()
    }

    no_bet_days = sorted(pipeline_dates - bet_days)

    return {
        "days_window": days,
        "total_pipeline_days": len(pipeline_dates),
        "bet_days": len(bet_days),
        "no_bet_days": len(no_bet_days),
        "no_bet_day_dates": no_bet_days,
    }


# ---------------------------------------------------------------------------
# Live-readiness
# ---------------------------------------------------------------------------

@router.get("/readiness")
def get_readiness() -> dict[str, Any]:
    """
    Live-readiness report.

    Decision-support only — does not enable real-money execution.
    The operator makes the final go/no-go call.
    """
    report = evaluate_readiness()
    return report.to_dict()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_latest_artifact() -> dict[str, Any] | None:
    """Load today's daily summary JSON artifact if it exists."""
    today = date.today().isoformat()
    path = Path(settings.daily_summary_dir) / f"{today}.json"
    if not path.exists():
        return None
    import json
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _pipeline_latest(db: Session, today: date) -> dict[str, Any]:
    run = (
        db.query(DailyPipelineRun)
        .filter(DailyPipelineRun.run_date == today)
        .order_by(DailyPipelineRun.id.desc())
        .first()
    )
    if run is None:
        return {"status": "no_run_today"}
    return {
        "status": run.status,
        "triggered_by": run.triggered_by,
        "duration_seconds": run.duration_seconds,
    }


def _bankroll_snapshot(db: Session) -> dict[str, Any]:
    latest = (
        db.query(BankrollLog)
        .order_by(BankrollLog.created_at.desc())
        .first()
    )
    if latest is None:
        return {"current": None}
    return {"current": round(latest.balance_after, 4), "last_event": latest.event_type}


def _recent_recommendations(db: Session, limit: int = 5) -> list[dict]:
    recs = (
        db.query(Recommendation)
        .order_by(Recommendation.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "side": r.side,
            "odds": r.recommended_odds,
            "stake_fraction": r.stake_fraction,
            "status": r.status,
        }
        for r in recs
    ]


def _freshness_warnings(db: Session) -> list[str]:
    """Quick freshness warning list (no thresholds applied here, raw ages returned)."""
    from db.models.odds_snapshots import OddsSnapshot
    now = datetime.now(tz=timezone.utc)
    latest_odds = (
        db.query(OddsSnapshot).order_by(OddsSnapshot.snapshot_time.desc()).first()
    )
    warnings = []
    if latest_odds is None:
        warnings.append("No odds snapshots found.")
    else:
        snap = latest_odds.snapshot_time
        if snap.tzinfo is None:
            snap = snap.replace(tzinfo=timezone.utc)
        age_h = (now - snap).total_seconds() / 3600
        if age_h > settings.odds_freshness_hours:
            warnings.append(f"Odds stale: {age_h:.1f}h since last snapshot.")
    return warnings
