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
  GET /dashboard/performance   — paper trade history + model accuracy
  GET /dashboard/roles         — today's role-audit artifacts (5 roles)
  GET /dashboard/calibration   — reliability diagram + per-phase Brier
"""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
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
from evaluation.clv_tracker import batch_clv, clv_summary
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
    cutoff = datetime.now(tz=UTC) - timedelta(days=days)

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
            "at": log.created_at.isoformat(),
            "balance": round(log.balance_after, 4),
            "event": log.event_type,
        }
        for log in logs
    ]

    balances = [log.balance_after for log in logs]
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
    from db.models.matches import Match
    from db.models.odds_snapshots import OddsSnapshot

    now = datetime.now(tz=UTC)
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
            dt = dt.replace(tzinfo=UTC)
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
    cutoff = datetime.now(tz=UTC) - timedelta(days=days)

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
# Performance — paper trade history + model accuracy
# ---------------------------------------------------------------------------

@router.get("/performance")
def get_performance(db: Session = Depends(get_db)) -> dict[str, Any]:
    """
    Full paper trade performance history and model accuracy stats.

    Returns:
      summary         — headline stats (win_rate, roi, brier, total bets)
      bets            — every recommendation with match details and outcome
      cumulative_pl   — sorted P&L series for equity curve charting
      model_runs      — latest run per model with brier/accuracy
    """
    from db.models.model_runs import ModelRun
    from db.models.teams import Team

    # --- team lookup map ---
    teams = {t.id: t.short_name for t in db.query(Team).all()}

    # --- all recommendations (all time) ---
    recs = (
        db.query(Recommendation)
        .order_by(Recommendation.created_at.asc())
        .all()
    )

    bets: list[dict] = []
    total = settled = wins = pending_count = void_count = 0
    total_pl = 0.0
    total_stake_units = 0.0
    cumulative: list[dict] = []
    running_pl = 0.0

    for rec in recs:
        total += 1
        if rec.status == "pending":
            pending_count += 1
        elif rec.status == "void":
            void_count += 1
        pred: Prediction | None = db.get(Prediction, rec.prediction_id)
        match: Match | None = db.get(Match, pred.match_id) if pred else None
        outcome: BetOutcome | None = rec.bet_outcome

        home_name = teams.get(match.home_team_id, f"T{match.home_team_id}") if match else "?"
        away_name = teams.get(match.away_team_id, f"T{match.away_team_id}") if match else "?"

        pl_units = None
        if outcome is not None:
            settled += 1
            won = bool(outcome.won)
            if won:
                wins += 1
            pl_units = outcome.profit_loss_units or 0.0
            total_pl += pl_units
            if rec.stake_fraction:
                total_stake_units += rec.stake_fraction
            running_pl += pl_units
            settled_at = (
                outcome.settled_at.isoformat()
                if outcome.settled_at else rec.created_at.isoformat()
            )
            cumulative.append({
                "date": settled_at,
                "cumulative_pl": round(running_pl, 4),
                "won": won,
                "match": f"{home_name} vs {away_name}",
            })

        bets.append({
            "id": rec.id,
            "created_at": rec.created_at.isoformat(),
            "match_time": match.match_time.isoformat() if match and match.match_time else None,
            "home_team": home_name,
            "away_team": away_name,
            "round": match.round_label if match else None,
            "venue": match.venue if match else None,
            "side": rec.side,
            "odds": rec.recommended_odds,
            "stake_fraction": round(rec.stake_fraction, 4),
            "status": rec.status,
            "home_win_prob": round(pred.home_win_prob, 4) if pred else None,
            "away_win_prob": round(pred.away_win_prob, 4) if pred else None,
            "edge": round(
                (pred.home_edge if rec.side == "home" else pred.away_edge) or 0.0, 4
            ) if pred else None,
            "outcome": {
                "won": bool(outcome.won) if outcome else None,
                "pl_units": (
                    round(outcome.profit_loss_units, 4)
                    if outcome and outcome.profit_loss_units is not None
                    else None
                ),
                "clv": (
                    round(outcome.clv, 4)
                    if outcome and outcome.clv is not None
                    else None
                ),
                "settled_at": (
                    outcome.settled_at.isoformat()
                    if outcome and outcome.settled_at
                    else None
                ),
            } if outcome else None,
        })

    win_rate = round(wins / settled, 4) if settled > 0 else None
    roi = round(total_pl / total_stake_units, 4) if total_stake_units > 0 else None
    active_bets = pending_count  # currently open bets

    # --- model run summaries (latest per model name) ---
    from sqlalchemy import func as sqlfunc
    subq = (
        db.query(
            ModelRun.model_name,
            sqlfunc.max(ModelRun.id).label("max_id"),
        )
        .filter(ModelRun.status == "completed")
        .group_by(ModelRun.model_name)
        .subquery()
    )
    latest_runs = (
        db.query(ModelRun)
        .join(subq, ModelRun.id == subq.c.max_id)
        .order_by(ModelRun.brier_score.asc())
        .all()
    )

    model_runs = [
        {
            "model": r.model_name,
            "brier": round(r.brier_score, 5) if r.brier_score else None,
            "accuracy": round(r.accuracy, 4) if r.accuracy else None,
            "log_loss": round(r.log_loss, 5) if r.log_loss else None,
            "trained_at": r.completed_at.isoformat() if r.completed_at else None,
        }
        for r in latest_runs
    ]

    return {
        "summary": {
            "total_bets": total,
            "settled": settled,
            "pending": active_bets,
            "void": void_count,
            "wins": wins,
            "losses": settled - wins,
            "win_rate_pct": round(win_rate * 100, 1) if win_rate is not None else None,
            "total_pl_units": round(total_pl, 4),
            "roi_pct": round(roi * 100, 1) if roi is not None else None,
        },
        "bets": bets,
        "cumulative_pl": cumulative,
        "model_runs": model_runs,
    }


# ---------------------------------------------------------------------------
# CLV (Closing Line Value)
# ---------------------------------------------------------------------------

@router.get("/clv")
def get_clv_summary(db: Session = Depends(get_db)) -> dict[str, Any]:
    """
    Closing Line Value summary across all settled recommendations.

    CLV > 0 on average means the model is consistently finding better odds
    than the market's final price — the strongest long-term edge signal.

    Fields:
      beat_closing_line : fraction of bets where CLV > 0 (target: >0.55)
      avg_clv_pct       : mean CLV as % of closing probability (target: >0)
      median_clv_pct    : median CLV% (robust to outlier games)
    """
    records = batch_clv(db)
    summary = clv_summary(records)
    return {"clv": summary}


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
# Role audits
# ---------------------------------------------------------------------------

@router.get("/roles")
def get_roles(day: str | None = None) -> dict[str, Any]:
    """
    Unified view of today's 5 role-audit artifacts from
    `storage/daily_summaries/roles/{role}/{YYYY-MM-DD}.json`.

    If `day` is omitted, returns today's artifacts. Missing artifacts return
    as {"available": false}. The front end renders one card per role.
    """
    import json
    target = day or date.today().isoformat()
    base = Path(settings.daily_summary_dir) / "roles"
    roles = ["data_steward", "feature_engineer", "model_engineer",
             "risk_manager", "quant_reviewer"]

    out: dict[str, Any] = {"day": target, "roles": {}}
    for role in roles:
        path = base / role / f"{target}.json"
        if not path.exists():
            # Fall back to most recent artifact for this role
            candidates = sorted((base / role).glob("*.json")) if (base / role).exists() else []
            path = candidates[-1] if candidates else None
        if path is None or not path.exists():
            out["roles"][role] = {"available": False}
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            out["roles"][role] = {"available": True, "source_file": path.name, **data}
        except Exception as exc:
            out["roles"][role] = {"available": False, "error": str(exc)}
    return out


# ---------------------------------------------------------------------------
# Calibration — reliability diagram + per-phase Brier
# ---------------------------------------------------------------------------

@router.get("/calibration")
def get_calibration(model: str | None = None, db: Session = Depends(get_db)) -> dict[str, Any]:
    """
    Reliability diagram data + per-phase Brier for a trained model.

    Bins predicted probabilities into 10 equal-width buckets, reports the
    observed home-win rate in each bucket, and splits Brier by season phase
    (preseason / early / mid / finals).

    Args:
      model: model_name from ModelRun. If omitted, uses the model with the
             lowest Brier among latest completed runs.
    """
    from backtesting.calibration import calibration_bins, expected_calibration_error
    from db.models.model_runs import ModelRun

    # Pick the model: explicit request, else best-by-Brier
    if model:
        run = (
            db.query(ModelRun)
            .filter(ModelRun.model_name == model, ModelRun.status == "completed")
            .order_by(ModelRun.created_at.desc())
            .first()
        )
    else:
        run = (
            db.query(ModelRun)
            .filter(ModelRun.status == "completed", ModelRun.brier_score.isnot(None))
            .order_by(ModelRun.brier_score.asc())
            .first()
        )
    if run is None:
        return {"available": False, "reason": "No completed ModelRun found."}

    rows = (
        db.query(Prediction, Match)
        .join(Match, Prediction.match_id == Match.id)
        .filter(Prediction.model_run_id == run.id)
        .filter(Match.result.isnot(None))
        .all()
    )
    if not rows:
        return {
            "available": False,
            "reason": f"No settled predictions for model_run id={run.id}.",
            "model_run": {"id": run.id, "model_name": run.model_name},
        }

    probs = [float(p.home_win_prob) for p, _ in rows]
    truths = [1 if m.result == "home" else 0 for _, m in rows]

    # Reliability bins
    bins_data = calibration_bins(truths, probs, n_bins=10)
    ece = expected_calibration_error(truths, probs)

    # Normalize bins_data into a simple list of dicts for the UI
    if hasattr(bins_data, "__iter__") and not isinstance(bins_data, dict):
        bins_list = []
        for b in bins_data:
            if hasattr(b, "__dict__"):
                bins_list.append({k: v for k, v in b.__dict__.items() if not k.startswith("_")})
            elif isinstance(b, dict):
                bins_list.append(b)
    else:
        bins_list = bins_data  # type: ignore[assignment]

    # Per-phase Brier
    phases: dict[str, list[tuple[float, int]]] = {
        "preseason": [], "early": [], "mid": [], "finals": [],
    }
    for pred, match in rows:
        phase = _phase_of(match)
        phases[phase].append((float(pred.home_win_prob), 1 if match.result == "home" else 0))
    per_phase: dict[str, dict[str, Any]] = {}
    for name, pairs in phases.items():
        if not pairs:
            per_phase[name] = {"n": 0, "brier": None, "accuracy": None}
            continue
        brier = sum((p - y) ** 2 for p, y in pairs) / len(pairs)
        acc = sum(1 for p, y in pairs if (p >= 0.5) == bool(y)) / len(pairs)
        per_phase[name] = {"n": len(pairs), "brier": round(brier, 5), "accuracy": round(acc, 4)}

    return {
        "available": True,
        "model_run": {
            "id": run.id,
            "model_name": run.model_name,
            "brier_score": run.brier_score,
            "trained_at": run.completed_at.isoformat() if run.completed_at else None,
        },
        "n_settled": len(rows),
        "ece": round(float(ece), 5) if ece is not None else None,
        "reliability_bins": bins_list,
        "per_phase": per_phase,
    }


def _phase_of(match: Match) -> str:
    if match.is_final:
        return "finals"
    r = match.round_number or 0
    if r <= 0:
        return "preseason"
    if r <= 6:
        return "early"
    return "mid"


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
    now = datetime.now(tz=UTC)
    latest_odds = (
        db.query(OddsSnapshot).order_by(OddsSnapshot.snapshot_time.desc()).first()
    )
    warnings = []
    if latest_odds is None:
        warnings.append("No odds snapshots found.")
    else:
        snap = latest_odds.snapshot_time
        if snap.tzinfo is None:
            snap = snap.replace(tzinfo=UTC)
        age_h = (now - snap).total_seconds() / 3600
        if age_h > settings.odds_freshness_hours:
            warnings.append(f"Odds stale: {age_h:.1f}h since last snapshot.")
    return warnings
