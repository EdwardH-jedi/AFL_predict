"""
orchestration/jobs/roles/model_engineer.py
-------------------------------------------
Role audit: Model Engineer.

Reports on trained models: latest ModelRun per model_name, metric deltas,
staleness, and whether a weekly retrain is due. Does NOT retrain —
train_models is the retrain entrypoint.

Output: storage/daily_summaries/roles/model_engineer/{YYYY-MM-DD}.json
"""

from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from loguru import logger
from sqlalchemy.orm import Session

from config.settings import get_settings
from db.models.model_runs import ModelRun
from db.session import db_session

settings = get_settings()

_RETRAIN_DUE_DAYS = 7

_last_result: dict[str, Any] | None = None


def get_last_result() -> dict[str, Any] | None:
    return _last_result


def run() -> None:
    global _last_result
    start = time.monotonic()
    today = date.today()
    logger.info("==> role:model_engineer starting")

    with db_session() as db:
        latest_per_model = _latest_per_model(db)
        history = _recent_runs(db, limit=20)

    report = {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "models": latest_per_model,
        "recent_runs": history,
        "leaderboard": _leaderboard(latest_per_model),
    }
    verdict, warnings = _verdict(latest_per_model)
    report["verdict"] = verdict
    report["warnings"] = warnings

    _write_artifact("model_engineer", today, report)
    _last_result = report

    duration = time.monotonic() - start
    logger.info(f"==> role:model_engineer {verdict.upper()} in {duration:.1f}s")


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def _latest_per_model(db: Session) -> list[dict[str, Any]]:
    """Return the most recent completed run per model_name, oldest-first."""
    all_runs: list[ModelRun] = (
        db.query(ModelRun)
        .filter(ModelRun.status == "completed")
        .order_by(ModelRun.created_at.desc())
        .all()
    )
    seen: dict[str, ModelRun] = {}
    for r in all_runs:
        seen.setdefault(r.model_name, r)

    now = datetime.now(tz=timezone.utc)
    out = []
    for name, run in seen.items():
        created = run.created_at.replace(tzinfo=timezone.utc) if run.created_at and run.created_at.tzinfo is None else run.created_at
        age_days = (now - created).total_seconds() / 86400 if created else None
        out.append({
            "model_name": name,
            "model_version": run.model_version,
            "brier_score": run.brier_score,
            "log_loss": run.log_loss,
            "accuracy": run.accuracy,
            "train_from_season": run.train_from_season,
            "train_to_season": run.train_to_season,
            "artifact_path": run.artifact_path,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "age_days": round(age_days, 2) if age_days is not None else None,
            "stale": (age_days or 0) > _RETRAIN_DUE_DAYS,
            "metadata_json": _parse_metadata(run.metadata_json),
        })
    return sorted(out, key=lambda r: (r["brier_score"] if r["brier_score"] is not None else 9.99))


def _recent_runs(db: Session, limit: int) -> list[dict[str, Any]]:
    runs: list[ModelRun] = (
        db.query(ModelRun)
        .order_by(ModelRun.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "model_name": r.model_name,
            "status": r.status,
            "brier_score": r.brier_score,
            "log_loss": r.log_loss,
            "accuracy": r.accuracy,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        }
        for r in runs
    ]


def _leaderboard(latest: list[dict[str, Any]]) -> list[dict[str, Any]]:
    valid = [r for r in latest if r["brier_score"] is not None]
    ranked = sorted(valid, key=lambda r: r["brier_score"])
    return [
        {
            "rank": i + 1,
            "model_name": r["model_name"],
            "brier_score": r["brier_score"],
            "log_loss": r["log_loss"],
            "accuracy": r["accuracy"],
            "age_days": r["age_days"],
        }
        for i, r in enumerate(ranked)
    ]


def _parse_metadata(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return {"_raw": raw[:200]}


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------

def _verdict(models: list[dict[str, Any]]) -> tuple[str, list[str]]:
    warnings: list[str] = []
    if not models:
        return "no_data", ["No completed ModelRun rows yet — run train_models."]

    stale = [m["model_name"] for m in models if m.get("stale")]
    if stale:
        warnings.append(f"Stale models (>{_RETRAIN_DUE_DAYS} days): {', '.join(stale)}. Retrain due.")

    required = {"logistic_baseline", "xgboost", "ensemble"}
    present = {m["model_name"] for m in models}
    missing = required - present
    if missing:
        warnings.append(f"Required models not yet trained: {sorted(missing)}.")

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
