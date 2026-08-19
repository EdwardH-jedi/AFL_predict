"""
orchestration/jobs/roles/quant_reviewer.py
-------------------------------------------
Role audit: Quant Reviewer.

Nightly independent evaluation. CLV sweep on settled recommendations,
beat-closing-line rate over the trailing 100 bets, per-phase Brier,
and a top-line verdict (improving / flat / regressing / insufficient_data).

This role has authority over accept/reject of other roles' changes.
Runs LAST in the daily chain — consumes everyone else's artifacts.

Output: storage/daily_summaries/roles/quant_reviewer/{YYYY-MM-DD}.json
"""

from __future__ import annotations

import json
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from loguru import logger
from sqlalchemy.orm import Session

from config.settings import get_settings
from db.models.bet_outcomes import BetOutcome
from db.models.matches import Match
from db.models.predictions import Prediction
from db.models.recommendations import Recommendation
from db.session import db_session

settings = get_settings()

_ROLLING_WINDOW = 100
_MIN_PHASE_SAMPLE = 30

_last_result: dict[str, Any] | None = None


def get_last_result() -> dict[str, Any] | None:
    return _last_result


def run() -> None:
    global _last_result
    start = time.monotonic()
    today = date.today()
    logger.info("==> role:quant_reviewer starting")

    with db_session() as db:
        clv_section = _clv_report(db)
        brier_section = _per_phase_brier(db)
        trend = _trend_verdict(db)
        readiness_gate = _clv_first_gate(clv_section, brier_section)

    report = {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "clv": clv_section,
        "per_phase_brier": brier_section,
        "trend": trend,
        "clv_first_gate": readiness_gate,
    }
    verdict, warnings = _verdict(report)
    report["verdict"] = verdict
    report["warnings"] = warnings

    _write_artifact("quant_reviewer", today, report)
    _last_result = report

    duration = time.monotonic() - start
    logger.info(f"==> role:quant_reviewer {verdict.upper()} in {duration:.1f}s")


# ---------------------------------------------------------------------------
# CLV
# ---------------------------------------------------------------------------

def _clv_report(db: Session) -> dict[str, Any]:
    try:
        from evaluation.clv_tracker import batch_clv, clv_summary
    except Exception as exc:
        return {"available": False, "reason": f"clv_tracker not importable: {exc}"}

    recs = (
        db.query(Recommendation)
        .filter(Recommendation.status == "settled")
        .order_by(Recommendation.created_at.desc())
        .limit(_ROLLING_WINDOW)
        .all()
    )
    if not recs:
        return {"available": True, "n_bets": 0, "reason": "no settled recommendations"}

    try:
        records = batch_clv(db, [r.id for r in recs])
        summary = clv_summary(records)
    except Exception as exc:
        return {"available": True, "error": f"batch_clv/clv_summary raised: {exc}"}

    return {
        "available": True,
        "window_size": _ROLLING_WINDOW,
        "n_evaluated": len(records),
        **summary,
    }


# ---------------------------------------------------------------------------
# Per-phase Brier (preseason / early / mid / finals)
# ---------------------------------------------------------------------------

def _per_phase_brier(db: Session) -> dict[str, Any]:
    rows = (
        db.query(Prediction, Match)
        .join(Match, Prediction.match_id == Match.id)
        .filter(Match.result.isnot(None))
        .all()
    )
    if not rows:
        return {"n": 0, "phases": {}}

    buckets: dict[str, list[tuple[float, int]]] = {
        "preseason": [], "early": [], "mid": [], "finals": [],
    }
    for pred, match in rows:
        p = getattr(pred, "home_win_prob", None) or getattr(pred, "probability", None)
        if p is None:
            continue
        y = 1 if match.result == "home" else 0
        phase = _phase_of(match)
        buckets[phase].append((float(p), y))

    phase_out = {}
    for phase, pairs in buckets.items():
        if len(pairs) < _MIN_PHASE_SAMPLE:
            phase_out[phase] = {"n": len(pairs), "brier": None, "note": "below min sample"}
            continue
        brier = sum((p - y) ** 2 for p, y in pairs) / len(pairs)
        phase_out[phase] = {
            "n": len(pairs),
            "brier": round(brier, 5),
            "accuracy": round(sum(1 for p, y in pairs if (p >= 0.5) == bool(y)) / len(pairs), 4),
        }
    return {"n": sum(len(v) for v in buckets.values()), "phases": phase_out}


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
# Trend (last 4 weeks vs prior 4 weeks)
# ---------------------------------------------------------------------------

def _trend_verdict(db: Session) -> dict[str, Any]:
    outcomes: list[BetOutcome] = (
        db.query(BetOutcome)
        .filter(BetOutcome.bet_source == "paper")
        .filter(BetOutcome.profit_loss_units.isnot(None))
        .order_by(BetOutcome.settled_at.desc().nullslast())
        .limit(200)
        .all()
    )
    if len(outcomes) < 20:
        return {"verdict": "insufficient_data", "n": len(outcomes)}

    split = len(outcomes) // 2
    recent = outcomes[:split]
    prior = outcomes[split:]
    recent_roi = _roi(recent)
    prior_roi = _roi(prior)
    delta = recent_roi - prior_roi
    if abs(delta) < 0.005:
        verdict = "flat"
    elif delta > 0:
        verdict = "improving"
    else:
        verdict = "regressing"
    return {
        "verdict": verdict,
        "recent_roi": round(recent_roi, 4),
        "prior_roi": round(prior_roi, 4),
        "delta_roi": round(delta, 4),
        "n_recent": len(recent),
        "n_prior": len(prior),
    }


def _roi(outcomes: list[BetOutcome]) -> float:
    staked = sum(float(o.stake_fraction or 0) for o in outcomes)
    pl = sum(float(o.profit_loss_units or 0) for o in outcomes)
    return pl / staked if staked > 0 else 0.0


# ---------------------------------------------------------------------------
# CLV-first readiness gate (advisory — Risk Manager enforces)
# ---------------------------------------------------------------------------

def _clv_first_gate(clv: dict[str, Any], phase: dict[str, Any]) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    passed_all = True

    n_clv = clv.get("n_with_clv") or clv.get("n_evaluated") or 0
    checks["sample_size"] = {"passed": n_clv >= settings.readiness_min_settled_bets, "n": n_clv}
    passed_all &= checks["sample_size"]["passed"]

    bc_rate = clv.get("beat_closing_line")
    checks["beat_closing_rate"] = {
        "passed": (bc_rate or 0) >= 0.52,
        "value": bc_rate,
        "threshold": 0.52,
    }
    passed_all &= checks["beat_closing_rate"]["passed"]

    avg_clv_pct = clv.get("avg_clv_pct")
    checks["avg_clv_pct"] = {
        "passed": (avg_clv_pct or 0) > 0.5,
        "value": avg_clv_pct,
        "threshold": 0.5,
    }
    passed_all &= checks["avg_clv_pct"]["passed"]

    return {"passed": passed_all, "checks": checks}


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------

def _verdict(report: dict[str, Any]) -> tuple[str, list[str]]:
    warnings: list[str] = []

    clv = report.get("clv", {})
    if clv.get("available") and (clv.get("avg_clv_pct") or 0) < 0:
        warnings.append(
            "CLV is negative over the trailing window — regime shift or broken feature."
        )

    trend = report.get("trend", {})
    if trend.get("verdict") == "regressing":
        warnings.append(f"ROI regressing (Δ={trend['delta_roi']:+.4f}) — investigate.")

    gate = report.get("clv_first_gate", {})
    if gate and not gate.get("passed"):
        warnings.append("CLV-first readiness gate NOT satisfied — live trial blocked.")

    if (clv.get("avg_clv_pct") or 0) < -1.0:
        return "critical", warnings
    if warnings:
        return "warn", warnings
    return "ok", warnings


def _write_artifact(role: str, today: date, report: dict[str, Any]) -> None:
    output_dir = Path(settings.daily_summary_dir) / "roles" / role
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{today.isoformat()}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    logger.info(f"role:{role} report → {path}")


if __name__ == "__main__":
    run()
    print(json.dumps(get_last_result(), indent=2, default=str))
