"""
evaluation/live_readiness.py
------------------------------
Live-readiness evaluator — decision-support report ONLY.

Evaluates whether the paper-trading system meets the minimum bar for
a restricted manual micro-trial.  Does NOT enable real-money execution.
The human operator makes the final go/no-go decision.

Checks performed:
  1. sample_size    — enough settled paper bets
  2. drawdown       — max bankroll drawdown acceptable
  3. calibration    — ECE on recent predictions acceptable
  4. ingestion_health — hard-dep job failures in last 7 days
  5. stale_data     — recurring stale-data warnings in last 7 days
  6. roi            — paper-trade ROI not catastrophically negative
  7. critical_todos — known unresolved critical items

Each check returns a ReadinessCheck with status: pass | warn | fail.

Overall ReadinessReport.overall:
  "ready"     — all checks pass or warn (no fails)
  "marginal"  — at least one warn, no fails
  "not_ready" — at least one fail

Usage:
    python -m evaluation.live_readiness
    # Or via API: GET /dashboard/readiness
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from loguru import logger
from sqlalchemy.orm import Session

from config.settings import get_settings
from db.models.bankroll_logs import BankrollLog
from db.models.bet_outcomes import BetOutcome
from db.models.daily_pipeline_runs import DailyPipelineRun
from db.models.match_features import MatchFeature
from db.models.pipeline_runs import PipelineRun
from db.models.predictions import Prediction
from db.models.recommendations import Recommendation
from db.session import db_session

settings = get_settings()

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

CHECK_STATUS = {"pass", "warn", "fail"}

# Known critical TODOs that must be resolved before live trial.
# Add items here when a new blocker is identified.
CRITICAL_TODOS: list[str] = [
    "Select best model by Brier score (not just most-recent) in generate_recommendations._load_best_model",
    "Load correct model class from artifact based on model_run.model_name",
    "Confirm TAB bookmaker is available in your Odds API subscription tier",
]


@dataclass
class ReadinessCheck:
    name: str
    status: str           # pass | warn | fail
    detail: str
    value: Any = None     # numeric value where applicable


@dataclass
class ReadinessReport:
    """Readiness evaluation result."""
    generated_at: datetime
    overall: str          # ready | marginal | not_ready
    checks: list[ReadinessCheck] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at.isoformat(),
            "overall": self.overall,
            "checks": [
                {
                    "name": c.name,
                    "status": c.status,
                    "detail": c.detail,
                    "value": c.value,
                }
                for c in self.checks
            ],
        }

    @property
    def is_ready(self) -> bool:
        return self.overall == "ready"


# ---------------------------------------------------------------------------
# Main evaluator
# ---------------------------------------------------------------------------

def evaluate() -> ReadinessReport:
    """
    Run all readiness checks against the live database.

    Returns:
        ReadinessReport with per-check results and overall status.
    """
    now = datetime.now(tz=timezone.utc)
    checks: list[ReadinessCheck] = []

    with db_session() as db:
        checks.append(_check_sample_size(db))
        checks.append(_check_drawdown(db))
        checks.append(_check_calibration(db))
        checks.append(_check_ingestion_health(db, now))
        checks.append(_check_stale_data(db, now))
        checks.append(_check_roi(db))

    checks.append(_check_critical_todos())

    overall = _derive_overall(checks)
    report = ReadinessReport(generated_at=now, overall=overall, checks=checks)
    logger.info(f"Live-readiness evaluation: {overall.upper()}")
    for c in checks:
        logger.info(f"  [{c.status.upper():4s}] {c.name}: {c.detail}")
    return report


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def _check_sample_size(db: Session) -> ReadinessCheck:
    """Require at least N settled paper bets."""
    n = db.query(BetOutcome).filter(BetOutcome.won != None).count()  # noqa: E711
    threshold = settings.readiness_min_settled_bets

    if n >= threshold:
        return ReadinessCheck(
            name="sample_size",
            status="pass",
            detail=f"{n} settled bets (threshold {threshold}).",
            value=n,
        )
    if n >= threshold * 0.5:
        return ReadinessCheck(
            name="sample_size",
            status="warn",
            detail=f"Only {n}/{threshold} settled bets. Keep paper trading.",
            value=n,
        )
    return ReadinessCheck(
        name="sample_size",
        status="fail",
        detail=f"Only {n}/{threshold} settled bets. Insufficient sample.",
        value=n,
    )


def _check_drawdown(db: Session) -> ReadinessCheck:
    """Max bankroll drawdown must be below threshold."""
    logs = (
        db.query(BankrollLog.balance_after)
        .order_by(BankrollLog.created_at.asc())
        .all()
    )
    if not logs:
        return ReadinessCheck(
            name="drawdown",
            status="warn",
            detail="No bankroll data. Cannot evaluate drawdown.",
            value=None,
        )

    balances = [row.balance_after for row in logs]
    peak = balances[0]
    max_dd = 0.0
    for b in balances:
        peak = max(peak, b)
        dd = (peak - b) / peak if peak > 0 else 0.0
        max_dd = max(max_dd, dd)

    threshold = settings.readiness_max_drawdown
    max_dd_pct = round(max_dd * 100, 2)

    if max_dd < threshold:
        return ReadinessCheck(
            name="drawdown",
            status="pass",
            detail=f"Max drawdown {max_dd_pct}% (threshold {threshold*100:.0f}%).",
            value=max_dd,
        )
    if max_dd < threshold * 1.25:
        return ReadinessCheck(
            name="drawdown",
            status="warn",
            detail=f"Max drawdown {max_dd_pct}% is near threshold {threshold*100:.0f}%.",
            value=max_dd,
        )
    return ReadinessCheck(
        name="drawdown",
        status="fail",
        detail=f"Max drawdown {max_dd_pct}% exceeds threshold {threshold*100:.0f}%.",
        value=max_dd,
    )


def _check_calibration(db: Session) -> ReadinessCheck:
    """
    Estimate calibration quality from the last 200 settled predictions.

    Uses a simplified ECE approximation (mean |prob - outcome|²).
    TODO: integrate with backtesting.calibration.expected_calibration_error
          once a dedicated calibration query is implemented.
    """
    from db.models.matches import Match

    # Get recent settled predictions linked to outcomes
    recent_preds = (
        db.query(Prediction)
        .join(Recommendation, Recommendation.prediction_id == Prediction.id)
        .join(BetOutcome, BetOutcome.recommendation_id == Recommendation.id)
        .filter(BetOutcome.won != None)  # noqa: E711
        .order_by(Prediction.id.desc())
        .limit(200)
        .all()
    )

    if len(recent_preds) < 30:
        return ReadinessCheck(
            name="calibration",
            status="warn",
            detail=f"Only {len(recent_preds)} settled predictions for calibration check (need 30+).",
            value=len(recent_preds),
        )

    # Rough Brier score as calibration proxy
    errors = []
    for pred in recent_preds:
        match: Match | None = db.get(Match, pred.match_id)
        if match is None or match.result is None:
            continue
        actual = 1.0 if match.result == "home" else 0.0
        errors.append((pred.home_win_prob - actual) ** 2)

    if not errors:
        return ReadinessCheck(
            name="calibration",
            status="warn",
            detail="Could not compute calibration — no matched results found.",
            value=None,
        )

    brier = round(math.fsum(errors) / len(errors), 6)
    threshold = settings.readiness_max_ece

    # Use Brier as ECE proxy: 0.25 = coin flip, lower is better
    if brier < threshold:
        return ReadinessCheck(
            name="calibration",
            status="pass",
            detail=f"Brier score {brier:.4f} (threshold {threshold}).",
            value=brier,
        )
    if brier < threshold * 1.5:
        return ReadinessCheck(
            name="calibration",
            status="warn",
            detail=f"Brier score {brier:.4f} near threshold {threshold}.",
            value=brier,
        )
    return ReadinessCheck(
        name="calibration",
        status="fail",
        detail=f"Brier score {brier:.4f} exceeds threshold {threshold}. Model may be miscalibrated.",
        value=brier,
    )


def _check_ingestion_health(db: Session, now: datetime) -> ReadinessCheck:
    """Count hard-dep job failures in the last 7 days."""
    cutoff = now - timedelta(days=7)
    hard_dep_jobs = {"ingest_afl", "ingest_tab_odds", "build_features"}

    fail_count = (
        db.query(PipelineRun)
        .filter(
            PipelineRun.job_name.in_(hard_dep_jobs),
            PipelineRun.status == "failed",
            PipelineRun.started_at >= cutoff,
        )
        .count()
    )

    threshold = settings.readiness_max_failed_jobs_7d

    if fail_count == 0:
        return ReadinessCheck(
            name="ingestion_health",
            status="pass",
            detail="No hard-dep job failures in last 7 days.",
            value=0,
        )
    if fail_count <= threshold:
        return ReadinessCheck(
            name="ingestion_health",
            status="warn",
            detail=f"{fail_count} hard-dep failure(s) in last 7 days (threshold {threshold}).",
            value=fail_count,
        )
    return ReadinessCheck(
        name="ingestion_health",
        status="fail",
        detail=f"{fail_count} hard-dep failures in last 7 days — pipeline is unstable.",
        value=fail_count,
    )


def _check_stale_data(db: Session, now: datetime) -> ReadinessCheck:
    """
    Check if there have been recurring partial_failure daily runs
    in the last 7 days (a proxy for repeated stale-data issues).
    """
    cutoff = now.date() - timedelta(days=7)
    partial_days = (
        db.query(DailyPipelineRun)
        .filter(
            DailyPipelineRun.run_date >= cutoff,
            DailyPipelineRun.status.in_(["partial_failure", "failed"]),
        )
        .count()
    )

    if partial_days == 0:
        return ReadinessCheck(
            name="stale_data",
            status="pass",
            detail="No failed/partial daily runs in last 7 days.",
            value=0,
        )
    if partial_days <= 2:
        return ReadinessCheck(
            name="stale_data",
            status="warn",
            detail=f"{partial_days} failed/partial pipeline day(s) in last 7 days.",
            value=partial_days,
        )
    return ReadinessCheck(
        name="stale_data",
        status="fail",
        detail=f"{partial_days} failed/partial days in last 7 days — data reliability concern.",
        value=partial_days,
    )


def _check_roi(db: Session) -> ReadinessCheck:
    """
    Check paper-trade ROI is not catastrophically negative.

    warn if ROI < -0.10 (losing 10c per $1 staked)
    fail if ROI < -0.25
    """
    outcomes = db.query(BetOutcome).filter(BetOutcome.won != None).all()  # noqa: E711
    if not outcomes:
        return ReadinessCheck(
            name="roi",
            status="warn",
            detail="No settled outcomes yet. Cannot compute ROI.",
            value=None,
        )

    total_pl = sum(o.profit_loss_units or 0.0 for o in outcomes)
    n = len(outcomes)
    # Approximate: each bet stakes 1 unit
    roi = round(total_pl / n, 6) if n > 0 else 0.0

    if roi >= -0.05:
        return ReadinessCheck(
            name="roi",
            status="pass",
            detail=f"Paper-trade ROI per unit: {roi:+.4f}.",
            value=roi,
        )
    if roi >= -0.25:
        return ReadinessCheck(
            name="roi",
            status="warn",
            detail=f"Paper-trade ROI per unit: {roi:+.4f}. Negative but not catastrophic.",
            value=roi,
        )
    return ReadinessCheck(
        name="roi",
        status="fail",
        detail=f"Paper-trade ROI per unit: {roi:+.4f}. Strategy is losing at an unacceptable rate.",
        value=roi,
    )


def _check_critical_todos() -> ReadinessCheck:
    """
    Report known unresolved critical TODOs that block live trial.
    These are manually maintained in CRITICAL_TODOS above.
    """
    if not CRITICAL_TODOS:
        return ReadinessCheck(
            name="critical_todos",
            status="pass",
            detail="No critical TODOs outstanding.",
            value=0,
        )
    detail = (
        f"{len(CRITICAL_TODOS)} critical TODO(s) unresolved:\n"
        + "\n".join(f"  - {t}" for t in CRITICAL_TODOS)
    )
    return ReadinessCheck(
        name="critical_todos",
        status="fail",
        detail=detail,
        value=len(CRITICAL_TODOS),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _derive_overall(checks: list[ReadinessCheck]) -> str:
    statuses = {c.status for c in checks}
    if "fail" in statuses:
        return "not_ready"
    if "warn" in statuses:
        return "marginal"
    return "ready"


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    report = evaluate()
    print(json.dumps(report.to_dict(), indent=2))
