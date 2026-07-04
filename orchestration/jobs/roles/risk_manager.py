"""
orchestration/jobs/roles/risk_manager.py
-----------------------------------------
Role audit: Risk Manager.

Inspects today's recommendations against staking, Kelly-cap, and edge-
threshold invariants, and surfaces the readiness gate status. Does NOT
create or modify recommendations.

Output: storage/daily_summaries/roles/risk_manager/{YYYY-MM-DD}.json
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

_last_result: dict[str, Any] | None = None


def get_last_result() -> dict[str, Any] | None:
    return _last_result


def run() -> None:
    global _last_result
    start = time.monotonic()
    today = date.today()
    logger.info("==> role:risk_manager starting")

    with db_session() as db:
        today_recs = _today_recs(db, today)
        rec_stats = _summarise_recs(today_recs)
        violations = _invariant_checks(today_recs)
        drawdown_info = _drawdown_snapshot(db)
        readiness = _readiness_snapshot()

    report = {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "paper_trade_only": settings.paper_trade_only,
        "max_kelly_fraction": settings.max_kelly_fraction,
        "min_edge_threshold": settings.min_edge_threshold,
        "today": rec_stats,
        "invariant_violations": violations,
        "drawdown": drawdown_info,
        "readiness": readiness,
    }
    verdict, warnings = _verdict(report)
    report["verdict"] = verdict
    report["warnings"] = warnings

    _write_artifact("risk_manager", today, report)
    _last_result = report

    duration = time.monotonic() - start
    logger.info(f"==> role:risk_manager {verdict.upper()} in {duration:.1f}s")


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def _today_recs(db: Session, today: date) -> list[dict[str, Any]]:
    start_dt = datetime.combine(today, datetime.min.time(), tzinfo=UTC)
    rows: list[Recommendation] = (
        db.query(Recommendation)
        .filter(Recommendation.created_at >= start_dt)
        .all()
    )
    out = []
    for r in rows:
        pred = db.get(Prediction, r.prediction_id) if r.prediction_id else None
        match = db.get(Match, pred.match_id) if pred and pred.match_id else None
        out.append({
            "id": r.id,
            "side": r.side,
            "recommended_odds": r.recommended_odds,
            "stake_fraction": r.stake_fraction,
            "stake_dollars": r.stake_dollars,
            "status": r.status,
            "paper_trade": r.paper_trade,
            "is_final": bool(match.is_final) if match else None,
            "season": match.season if match else None,
        })
    return out


def _summarise_recs(recs: list[dict[str, Any]]) -> dict[str, Any]:
    if not recs:
        return {"n": 0, "sides": {}, "kelly_max": None, "kelly_mean": None, "n_finals": 0}
    kellys = [r["stake_fraction"] for r in recs if r["stake_fraction"] is not None]
    sides: dict[str, int] = {}
    for r in recs:
        sides[r["side"]] = sides.get(r["side"], 0) + 1
    return {
        "n": len(recs),
        "sides": sides,
        "kelly_max": max(kellys) if kellys else None,
        "kelly_mean": round(sum(kellys) / len(kellys), 6) if kellys else None,
        "n_finals": sum(1 for r in recs if r.get("is_final")),
        "n_paper": sum(1 for r in recs if r["paper_trade"]),
        "n_live": sum(1 for r in recs if not r["paper_trade"]),
    }


def _invariant_checks(recs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    cap = settings.max_kelly_fraction
    for r in recs:
        kf = r.get("stake_fraction")
        if kf is not None and kf > cap + 1e-9:
            violations.append({
                "rec_id": r["id"],
                "rule": "kelly_cap",
                "detail": f"stake_fraction={kf:.4f} exceeds max_kelly_fraction={cap}",
            })
        if not r["paper_trade"] and settings.paper_trade_only:
            violations.append({
                "rec_id": r["id"],
                "rule": "paper_trade_only",
                "detail": "Live recommendation created while PAPER_TRADE_ONLY=true",
            })
    return violations


def _drawdown_snapshot(db: Session) -> dict[str, Any]:
    """Running max drawdown on the paper bankroll using profit_loss_units."""
    outcomes: list[BetOutcome] = (
        db.query(BetOutcome)
        .filter(BetOutcome.bet_source == "paper")
        .filter(BetOutcome.profit_loss_units.isnot(None))
        .order_by(BetOutcome.settled_at.asc().nullslast(), BetOutcome.id.asc())
        .all()
    )
    if not outcomes:
        return {"n_settled": 0, "max_drawdown": None, "current_drawdown": None}

    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for o in outcomes:
        equity += float(o.profit_loss_units or 0)
        peak = max(peak, equity)
        dd = peak - equity
        max_dd = max(max_dd, dd)
    return {
        "n_settled": len(outcomes),
        "cumulative_units": round(equity, 4),
        "peak_units": round(peak, 4),
        "current_drawdown_units": round(peak - equity, 4),
        "max_drawdown_units": round(max_dd, 4),
    }


def _readiness_snapshot() -> dict[str, Any]:
    try:
        from evaluation.live_readiness import evaluate as evaluate_readiness
    except Exception as exc:
        return {"available": False, "reason": f"evaluate_readiness not importable: {exc}"}
    try:
        report = evaluate_readiness()
        if hasattr(report, "to_dict"):
            return {"available": True, **report.to_dict()}
        if isinstance(report, dict):
            return {"available": True, **report}
        return {"available": True, "overall": getattr(report, "overall", None)}
    except Exception as exc:
        return {"available": True, "error": f"evaluate_readiness raised: {exc}"}


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------

def _verdict(report: dict[str, Any]) -> tuple[str, list[str]]:
    warnings: list[str] = []
    if report["invariant_violations"]:
        warnings.append(f"{len(report['invariant_violations'])} staking invariant violation(s).")

    readiness = report.get("readiness", {})
    if readiness.get("available") and str(readiness.get("overall", "")).lower() == "ready":
        if (report.get("drawdown", {}).get("n_settled") or 0) < settings.readiness_min_settled_bets:
            warnings.append(
                "Readiness reports 'ready' but settled-bet sample is below the CLV-gate minimum."
            )

    if report["invariant_violations"]:
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
