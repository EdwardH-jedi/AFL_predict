"""
api/routes/dashboard_ui.py
---------------------------
Typed endpoints for the React frontend under /api/dashboard/*.

Separate from the legacy /dashboard/* router (consumed by static/dashboard.html)
so that UI evolution does not risk breaking the existing HTML dashboard.

Endpoints:
  GET /api/dashboard/today-picks      — upcoming matches + recommendations + bankroll
  GET /api/dashboard/performance      — season summary + recent settled + bankroll + model compare
  GET /api/dashboard/odds-tracker     — current round odds comparison + per-match snapshot history
  GET /api/dashboard/backtest-summary — latest daily summary artifact + ensemble weights
  GET /api/dashboard/system-status    — job freshness, odds-API usage, DB row counts, readiness
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func as sqlfunc

from api.dependencies import DbSession
from config.settings import get_settings
from db.models.bankroll_logs import BankrollLog
from db.models.bet_outcomes import BetOutcome
from db.models.matches import Match
from db.models.model_runs import ModelRun
from db.models.odds_snapshots import OddsSnapshot
from db.models.pipeline_runs import PipelineRun
from db.models.predictions import Prediction
from db.models.recommendations import Recommendation
from db.models.teams import Team
from evaluation.live_readiness import evaluate as evaluate_readiness

settings = get_settings()
router = APIRouter()

_PAPER_INITIAL = 1000.0
_ODDS_API_MONTHLY_LIMIT = 500  # free tier at the-odds-api.com

# Jobs expected to run daily — used to derive node status.
_CORE_JOBS = [
    "ingest_afl",
    "ingest_tab_odds",
    "build_features",
    "generate_recommendations",
    "settle_results",
]


# ---------------------------------------------------------------------------
# Shared response fragments
# ---------------------------------------------------------------------------

class BankrollSnapshot(BaseModel):
    paper_balance: float
    paper_initial: float
    paper_return_pct: float | None
    live_balance_aud: float | None


class PickRecommendation(BaseModel):
    rec_id: int
    side: str
    recommended_odds: float
    edge: float | None
    kelly_fraction: float
    suggested_stake_aud: float | None
    using_live_bankroll: bool


class PickMatch(BaseModel):
    match_id: int
    home_team: str
    away_team: str
    venue: str | None
    match_time: str | None
    minutes_until: int | None
    round_label: str | None
    is_final: bool
    home_win_prob: float
    away_win_prob: float
    recommendation: PickRecommendation | None


class TodayPicksResponse(BaseModel):
    generated_at: str
    days_ahead: int
    n_matches: int
    next_match_minutes: int | None
    bankroll: BankrollSnapshot
    picks: list[PickMatch]


# --- performance ---

class PerformanceSummary(BaseModel):
    total_bets: int
    settled: int
    pending: int
    wins: int
    losses: int
    win_rate_pct: float | None
    total_pl_units: float
    roi_pct: float | None
    brier_best: float | None


class RecentMatch(BaseModel):
    match_id: int
    home_team: str
    away_team: str
    match_time: str | None
    round_label: str | None
    predicted_side: str
    predicted_prob: float
    actual_result: str | None
    correct: bool | None


class BankrollPoint(BaseModel):
    round_label: str
    balance: float


class ModelAccuracy(BaseModel):
    model_name: str
    accuracy: float | None
    brier: float | None
    log_loss: float | None
    trained_at: str | None


class PerformanceResponse(BaseModel):
    summary: PerformanceSummary
    recent_matches: list[RecentMatch]
    bankroll_history: list[BankrollPoint]
    model_comparison: list[ModelAccuracy]


# --- odds-tracker ---

class OddsHistoryPoint(BaseModel):
    at: str
    home_odds: float | None
    away_odds: float | None
    bookmaker: str


class OddsTrackerMatch(BaseModel):
    match_id: int
    home_team: str
    away_team: str
    match_time: str | None
    round_label: str | None
    tab_home_odds: float | None
    tab_away_odds: float | None
    tab_home_implied: float | None
    tab_away_implied: float | None
    model_home_prob: float | None
    model_away_prob: float | None
    home_edge: float | None
    away_edge: float | None
    history: list[OddsHistoryPoint]


class OddsTrackerResponse(BaseModel):
    round_label: str | None
    round_number: int | None
    n_matches: int
    matches: list[OddsTrackerMatch]


# --- backtest-summary ---

class EnsembleWeights(BaseModel):
    logistic: float
    elo: float
    xgboost: float
    poisson: float


class BacktestSummaryResponse(BaseModel):
    available: bool
    source_date: str | None
    pipeline_status: str | None
    season_roi_pct: float | None
    bankroll_current: float | None
    bankroll_peak: float | None
    drawdown: float | None
    n_settled: int
    n_pending: int
    ensemble_weights: EnsembleWeights
    raw_summary: dict[str, Any] | None


# --- system-status ---

class JobStatus(BaseModel):
    job_name: str
    last_status: str | None
    last_run_at: str | None
    age_hours: float | None
    retry_count: int | None


class DbRowCounts(BaseModel):
    matches: int
    predictions: int
    recommendations: int
    odds_snapshots: int
    bet_outcomes: int
    bankroll_logs: int


class OddsApiUsage(BaseModel):
    monthly_limit: int
    monthly_used_estimate: int
    monthly_remaining_estimate: int
    month: str
    note: str


class ReadinessCheckDto(BaseModel):
    name: str
    status: str
    detail: str


class SystemStatusResponse(BaseModel):
    checked_at: str
    node_role: str
    phase: str
    jobs: list[JobStatus]
    db_rows: DbRowCounts
    odds_api: OddsApiUsage
    readiness_overall: str
    readiness_checks: list[ReadinessCheckDto]


# ---------------------------------------------------------------------------
# GET /api/dashboard/today-picks
# ---------------------------------------------------------------------------

@router.get("/today-picks", response_model=TodayPicksResponse)
def today_picks(db: DbSession, days_ahead: int = 3) -> TodayPicksResponse:
    days_ahead = max(1, min(days_ahead, 14))
    now = datetime.now(tz=UTC)
    horizon = now + timedelta(days=days_ahead)

    matches = (
        db.query(Match)
        .filter(Match.match_time >= now, Match.match_time <= horizon, Match.result.is_(None))
        .order_by(Match.match_time.asc())
        .all()
    )

    live_balance = _latest_balance(db, "live")
    paper_balance = _latest_balance(db, "paper") or _PAPER_INITIAL
    stake_bankroll = live_balance if live_balance is not None else paper_balance
    using_live = live_balance is not None

    team_map = {t.id: t.short_name for t in db.query(Team).all()}
    picks: list[PickMatch] = []

    for m in matches:
        pred = (
            db.query(Prediction)
            .filter(Prediction.match_id == m.id)
            .order_by(Prediction.id.desc())
            .first()
        )
        if pred is None:
            continue
        rec = (
            db.query(Recommendation)
            .filter(
                Recommendation.prediction_id == pred.id,
                Recommendation.status == "pending",
            )
            .first()
        )

        mt = m.match_time
        if mt and mt.tzinfo is None:
            mt = mt.replace(tzinfo=UTC)
        minutes_until = int((mt - now).total_seconds() / 60) if mt else None

        rec_dto: PickRecommendation | None = None
        if rec is not None:
            edge = pred.home_edge if rec.side == "home" else pred.away_edge
            suggested = (
                round(rec.stake_fraction * stake_bankroll, 2)
                if rec.stake_fraction and stake_bankroll else None
            )
            rec_dto = PickRecommendation(
                rec_id=rec.id,
                side=rec.side,
                recommended_odds=round(rec.recommended_odds, 3),
                edge=round(edge, 4) if edge is not None else None,
                kelly_fraction=round(rec.stake_fraction, 4),
                suggested_stake_aud=suggested,
                using_live_bankroll=using_live,
            )

        picks.append(PickMatch(
            match_id=m.id,
            home_team=team_map.get(m.home_team_id, f"T{m.home_team_id}"),
            away_team=team_map.get(m.away_team_id, f"T{m.away_team_id}"),
            venue=m.venue,
            match_time=mt.isoformat() if mt else None,
            minutes_until=minutes_until,
            round_label=m.round_label or (f"Round {m.round_number}" if m.round_number else None),
            is_final=bool(m.is_final),
            home_win_prob=round(pred.home_win_prob, 4),
            away_win_prob=round(pred.away_win_prob, 4),
            recommendation=rec_dto,
        ))

    next_mins = picks[0].minutes_until if picks else None

    return TodayPicksResponse(
        generated_at=now.isoformat(),
        days_ahead=days_ahead,
        n_matches=len(picks),
        next_match_minutes=next_mins,
        bankroll=BankrollSnapshot(
            paper_balance=round(paper_balance, 2),
            paper_initial=_PAPER_INITIAL,
            paper_return_pct=_return_pct(paper_balance, _PAPER_INITIAL),
            live_balance_aud=round(live_balance, 2) if live_balance is not None else None,
        ),
        picks=picks,
    )


# ---------------------------------------------------------------------------
# GET /api/dashboard/performance
# ---------------------------------------------------------------------------

@router.get("/performance", response_model=PerformanceResponse)
def performance(db: DbSession) -> PerformanceResponse:
    team_map = {t.id: t.short_name for t in db.query(Team).all()}

    recs = db.query(Recommendation).order_by(Recommendation.created_at.asc()).all()
    total = len(recs)
    settled = wins = pending = 0
    total_pl = 0.0
    total_stake_units = 0.0

    for rec in recs:
        if rec.status == "pending":
            pending += 1
        outcome: BetOutcome | None = rec.bet_outcome
        if outcome is None:
            continue
        settled += 1
        if bool(outcome.won):
            wins += 1
        if outcome.profit_loss_units is not None:
            total_pl += outcome.profit_loss_units
        if rec.stake_fraction:
            total_stake_units += rec.stake_fraction

    win_rate_pct = round(wins / settled * 100, 1) if settled > 0 else None
    roi_pct = round(total_pl / total_stake_units * 100, 1) if total_stake_units > 0 else None

    # Recent 10 settled matches with prediction vs actual
    recent_rows = (
        db.query(Prediction, Match)
        .join(Match, Prediction.match_id == Match.id)
        .filter(Match.result.isnot(None))
        .order_by(Match.match_time.desc())
        .limit(10)
        .all()
    )
    recent: list[RecentMatch] = []
    for pred, m in recent_rows:
        predicted_side = "home" if pred.home_win_prob >= 0.5 else "away"
        predicted_prob = (
            pred.home_win_prob if predicted_side == "home" else pred.away_win_prob
        )
        correct = (predicted_side == m.result) if m.result in ("home", "away") else None
        recent.append(RecentMatch(
            match_id=m.id,
            home_team=team_map.get(m.home_team_id, f"T{m.home_team_id}"),
            away_team=team_map.get(m.away_team_id, f"T{m.away_team_id}"),
            match_time=m.match_time.isoformat() if m.match_time else None,
            round_label=m.round_label or (f"Round {m.round_number}" if m.round_number else None),
            predicted_side=predicted_side,
            predicted_prob=round(predicted_prob, 4),
            actual_result=m.result,
            correct=correct,
        ))

    # Bankroll history aggregated per round (paper).
    bankroll_history = _bankroll_per_round(db)

    # Model comparison — latest completed run per model_name.
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
        .order_by(ModelRun.brier_score.asc().nullslast())
        .all()
    )
    model_cmp = [
        ModelAccuracy(
            model_name=r.model_name,
            accuracy=round(r.accuracy, 4) if r.accuracy is not None else None,
            brier=round(r.brier_score, 5) if r.brier_score is not None else None,
            log_loss=round(r.log_loss, 5) if r.log_loss is not None else None,
            trained_at=r.completed_at.isoformat() if r.completed_at else None,
        )
        for r in latest_runs
    ]
    brier_best = next(
        (m.brier for m in model_cmp if m.brier is not None), None
    )

    return PerformanceResponse(
        summary=PerformanceSummary(
            total_bets=total,
            settled=settled,
            pending=pending,
            wins=wins,
            losses=settled - wins,
            win_rate_pct=win_rate_pct,
            total_pl_units=round(total_pl, 4),
            roi_pct=roi_pct,
            brier_best=brier_best,
        ),
        recent_matches=recent,
        bankroll_history=bankroll_history,
        model_comparison=model_cmp,
    )


# ---------------------------------------------------------------------------
# GET /api/dashboard/odds-tracker
# ---------------------------------------------------------------------------

@router.get("/odds-tracker", response_model=OddsTrackerResponse)
def odds_tracker(db: DbSession) -> OddsTrackerResponse:
    now = datetime.now(tz=UTC)
    team_map = {t.id: t.short_name for t in db.query(Team).all()}

    # Current round = the smallest round_number among upcoming unresolved matches.
    current_match = (
        db.query(Match)
        .filter(Match.match_time >= now, Match.result.is_(None))
        .order_by(Match.match_time.asc())
        .first()
    )
    if current_match is None:
        return OddsTrackerResponse(
            round_label=None, round_number=None, n_matches=0, matches=[]
        )

    matches = (
        db.query(Match)
        .filter(
            Match.season == current_match.season,
            Match.round_number == current_match.round_number,
        )
        .order_by(Match.match_time.asc())
        .all()
    )

    rows: list[OddsTrackerMatch] = []
    for m in matches:
        latest_snap = (
            db.query(OddsSnapshot)
            .filter(OddsSnapshot.match_id == m.id)
            .order_by(OddsSnapshot.snapshot_time.desc())
            .first()
        )
        history_rows = (
            db.query(OddsSnapshot)
            .filter(OddsSnapshot.match_id == m.id)
            .order_by(OddsSnapshot.snapshot_time.asc())
            .limit(200)
            .all()
        )
        history = [
            OddsHistoryPoint(
                at=s.snapshot_time.isoformat(),
                home_odds=s.home_odds,
                away_odds=s.away_odds,
                bookmaker=s.bookmaker,
            )
            for s in history_rows
        ]

        pred = (
            db.query(Prediction)
            .filter(Prediction.match_id == m.id)
            .order_by(Prediction.id.desc())
            .first()
        )

        rows.append(OddsTrackerMatch(
            match_id=m.id,
            home_team=team_map.get(m.home_team_id, f"T{m.home_team_id}"),
            away_team=team_map.get(m.away_team_id, f"T{m.away_team_id}"),
            match_time=m.match_time.isoformat() if m.match_time else None,
            round_label=m.round_label or f"Round {m.round_number}",
            tab_home_odds=latest_snap.home_odds if latest_snap else None,
            tab_away_odds=latest_snap.away_odds if latest_snap else None,
            tab_home_implied=latest_snap.home_implied_prob if latest_snap else None,
            tab_away_implied=latest_snap.away_implied_prob if latest_snap else None,
            model_home_prob=round(pred.home_win_prob, 4) if pred else None,
            model_away_prob=round(pred.away_win_prob, 4) if pred else None,
            home_edge=round(pred.home_edge, 4) if pred and pred.home_edge is not None else None,
            away_edge=round(pred.away_edge, 4) if pred and pred.away_edge is not None else None,
            history=history,
        ))

    return OddsTrackerResponse(
        round_label=current_match.round_label or f"Round {current_match.round_number}",
        round_number=current_match.round_number,
        n_matches=len(rows),
        matches=rows,
    )


# ---------------------------------------------------------------------------
# GET /api/dashboard/backtest-summary
# ---------------------------------------------------------------------------

@router.get("/backtest-summary", response_model=BacktestSummaryResponse)
def backtest_summary(db: DbSession) -> BacktestSummaryResponse:
    weights = EnsembleWeights(
        logistic=settings.ensemble_weight_logistic,
        elo=settings.ensemble_weight_elo,
        xgboost=settings.ensemble_weight_xgboost,
        poisson=settings.ensemble_weight_poisson,
    )

    artifact, source_date = _load_latest_summary_artifact()
    if artifact is None:
        return BacktestSummaryResponse(
            available=False,
            source_date=None,
            pipeline_status=None,
            season_roi_pct=None,
            bankroll_current=None,
            bankroll_peak=None,
            drawdown=None,
            n_settled=0,
            n_pending=0,
            ensemble_weights=weights,
            raw_summary=None,
        )

    pipeline_block = artifact.get("pipeline") or {}
    bankroll_block = artifact.get("bankroll") or {}
    recs_block = artifact.get("recommendations") or []
    recent_block = artifact.get("recent_outcomes") or []

    n_pending = sum(1 for r in recs_block if r.get("status") == "pending")
    n_settled = sum(1 for r in recent_block if r.get("won") is not None)

    # Season ROI: compute from settled BetOutcome rows this calendar year.
    year_start = datetime(datetime.now(tz=UTC).year, 1, 1, tzinfo=UTC)
    settled_outcomes = (
        db.query(BetOutcome)
        .filter(BetOutcome.won.isnot(None), BetOutcome.settled_at >= year_start)
        .all()
    )
    total_pl = sum(o.profit_loss_units or 0.0 for o in settled_outcomes)
    # approximate total staked using linked recommendation stake_fraction
    total_staked = 0.0
    for o in settled_outcomes:
        rec = db.get(Recommendation, o.recommendation_id) if o.recommendation_id else None
        if rec and rec.stake_fraction:
            total_staked += rec.stake_fraction
    season_roi_pct = (
        round(total_pl / total_staked * 100, 2) if total_staked > 0 else None
    )

    return BacktestSummaryResponse(
        available=True,
        source_date=source_date,
        pipeline_status=pipeline_block.get("status"),
        season_roi_pct=season_roi_pct,
        bankroll_current=bankroll_block.get("current_balance"),
        bankroll_peak=bankroll_block.get("peak_balance"),
        drawdown=bankroll_block.get("drawdown"),
        n_settled=n_settled,
        n_pending=n_pending,
        ensemble_weights=weights,
        raw_summary=artifact,
    )


# ---------------------------------------------------------------------------
# GET /api/dashboard/system-status
# ---------------------------------------------------------------------------

@router.get("/system-status", response_model=SystemStatusResponse)
def system_status(db: DbSession) -> SystemStatusResponse:
    now = datetime.now(tz=UTC)

    # Per-job last successful run
    jobs: list[JobStatus] = []
    for job in _CORE_JOBS:
        last = (
            db.query(PipelineRun)
            .filter(PipelineRun.job_name == job)
            .order_by(PipelineRun.started_at.desc())
            .first()
        )
        if last is None:
            jobs.append(JobStatus(
                job_name=job, last_status=None, last_run_at=None,
                age_hours=None, retry_count=None,
            ))
            continue
        started = last.started_at
        if started and started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        age = (
            round((now - started).total_seconds() / 3600, 2)
            if started else None
        )
        jobs.append(JobStatus(
            job_name=job,
            last_status=last.status,
            last_run_at=started.isoformat() if started else None,
            age_hours=age,
            retry_count=last.retry_count,
        ))

    # DB row counts
    db_rows = DbRowCounts(
        matches=db.query(sqlfunc.count(Match.id)).scalar() or 0,
        predictions=db.query(sqlfunc.count(Prediction.id)).scalar() or 0,
        recommendations=db.query(sqlfunc.count(Recommendation.id)).scalar() or 0,
        odds_snapshots=db.query(sqlfunc.count(OddsSnapshot.id)).scalar() or 0,
        bet_outcomes=db.query(sqlfunc.count(BetOutcome.id)).scalar() or 0,
        bankroll_logs=db.query(sqlfunc.count(BankrollLog.id)).scalar() or 0,
    )

    # Odds API usage — estimated from pipeline run history for this calendar month.
    month_start = datetime(now.year, now.month, 1, tzinfo=UTC)
    odds_used = (
        db.query(sqlfunc.count(PipelineRun.id))
        .filter(
            PipelineRun.job_name == "ingest_tab_odds",
            PipelineRun.status == "success",
            PipelineRun.started_at >= month_start,
        )
        .scalar() or 0
    )
    odds_remaining = max(0, _ODDS_API_MONTHLY_LIMIT - int(odds_used))
    odds_api = OddsApiUsage(
        monthly_limit=_ODDS_API_MONTHLY_LIMIT,
        monthly_used_estimate=int(odds_used),
        monthly_remaining_estimate=odds_remaining,
        month=f"{now.year}-{now.month:02d}",
        note=(
            "Estimate: counts successful ingest_tab_odds runs this month. "
            "Replace with x-requests-remaining header once persisted."
        ),
    )

    # Phase label (derive from settled bet count thresholds)
    settled_count = db.query(BetOutcome).filter(BetOutcome.won.isnot(None)).count()
    phase = _derive_phase(settled_count)

    # Readiness
    try:
        report = evaluate_readiness()
        readiness_overall = report.overall
        readiness_checks = [
            ReadinessCheckDto(name=c.name, status=c.status, detail=c.detail)
            for c in report.checks
        ]
    except Exception as exc:  # readiness evaluator depends on external state
        readiness_overall = "unknown"
        readiness_checks = [
            ReadinessCheckDto(
                name="evaluator",
                status="fail",
                detail=f"{type(exc).__name__}: {exc}",
            )
        ]

    return SystemStatusResponse(
        checked_at=now.isoformat(),
        node_role=settings.node_role,
        phase=phase,
        jobs=jobs,
        db_rows=db_rows,
        odds_api=odds_api,
        readiness_overall=readiness_overall,
        readiness_checks=readiness_checks,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _latest_balance(db, log_type: str) -> float | None:
    row = (
        db.query(BankrollLog)
        .filter(BankrollLog.log_type == log_type)
        .order_by(BankrollLog.created_at.desc())
        .first()
    )
    return float(row.balance_after) if row else None


def _return_pct(current: float, initial: float) -> float | None:
    if initial and initial > 0:
        return round((current - initial) / initial * 100, 2)
    return None


def _bankroll_per_round(db) -> list[BankrollPoint]:
    """Latest paper bankroll balance for each round that has at least one settled bet."""
    # Map settled recommendation_id -> round_label
    rounds_by_rec: dict[int, str] = {}
    rows = (
        db.query(Recommendation, Match)
        .join(Prediction, Prediction.id == Recommendation.prediction_id)
        .join(Match, Match.id == Prediction.match_id)
        .all()
    )
    for rec, m in rows:
        label = m.round_label or (f"R{m.round_number}" if m.round_number else "R?")
        rounds_by_rec[rec.id] = label

    # Walk paper bankroll logs in order, keep the last balance for each round.
    logs = (
        db.query(BankrollLog)
        .filter(BankrollLog.log_type == "paper")
        .order_by(BankrollLog.created_at.asc())
        .all()
    )
    if not logs:
        return []
    per_round: dict[str, float] = {}
    order: list[str] = []
    for log in logs:
        label = rounds_by_rec.get(log.recommendation_id or -1, "Seed")
        if label not in per_round:
            order.append(label)
        per_round[label] = round(log.balance_after, 4)
    return [BankrollPoint(round_label=lbl, balance=per_round[lbl]) for lbl in order]


def _load_latest_summary_artifact() -> tuple[dict[str, Any] | None, str | None]:
    base = Path(settings.daily_summary_dir)
    if not base.exists():
        return None, None
    candidates = sorted(base.glob("*.json"))
    if not candidates:
        return None, None
    path = candidates[-1]
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f), path.stem
    except Exception:
        return None, path.stem


def _derive_phase(n_settled: int) -> str:
    """Coarse phase label from settled-bet count. Override in future with a settings-driven map."""
    if n_settled >= settings.readiness_min_settled_bets:
        return "live_trial_candidate"
    if n_settled >= 50:
        return "paper_trade_maturing"
    if n_settled >= 10:
        return "paper_trade_early"
    return "bootstrap"
