"""
orchestration/jobs/roles/data_steward.py
-----------------------------------------
Role audit: Data Steward.

Reports coverage for every external data source the model depends on —
historical bookmaker odds, player lineups, weather, upcoming-match odds.
Does NOT run backfills; that is an explicit human/agent decision.

Output: storage/daily_summaries/roles/data_steward/{YYYY-MM-DD}.json
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
from db.models.matches import Match
from db.models.odds_snapshots import OddsSnapshot
from db.session import db_session

settings = get_settings()

_last_result: dict[str, Any] | None = None


def get_last_result() -> dict[str, Any] | None:
    return _last_result


def run() -> None:
    global _last_result
    start = time.monotonic()
    today = date.today()
    logger.info("==> role:data_steward starting")

    with db_session() as db:
        report = {
            "generated_at": datetime.now(tz=UTC).isoformat(),
            "odds": _odds_coverage(db),
            "player_lineups": _player_lineup_coverage(db),
            "weather": _weather_coverage(db),
            "upcoming": _upcoming_gaps(db),
        }

    verdict, warnings = _verdict(report)
    report["verdict"] = verdict
    report["warnings"] = warnings

    _write_artifact("data_steward", today, report)
    _last_result = report

    duration = time.monotonic() - start
    logger.info(f"==> role:data_steward {verdict.upper()} in {duration:.1f}s "
                f"({len(warnings)} warning(s))")


# ---------------------------------------------------------------------------
# Coverage queries
# ---------------------------------------------------------------------------

def _odds_coverage(db: Session) -> dict[str, Any]:
    """Per-season count of settled matches with vs. without any odds snapshot."""
    settled = db.query(Match).filter(Match.result.isnot(None)).all()
    total_settled = len(settled)

    covered_match_ids = {
        row.match_id for row in db.query(OddsSnapshot.match_id).distinct().all()
    }
    settled_ids = {m.id for m in settled}
    covered = settled_ids & covered_match_ids
    missing = settled_ids - covered_match_ids

    by_season: dict[int, dict[str, int]] = {}
    for m in settled:
        slot = by_season.setdefault(m.season, {"total": 0, "covered": 0, "missing": 0})
        slot["total"] += 1
        if m.id in covered:
            slot["covered"] += 1
        else:
            slot["missing"] += 1

    return {
        "settled_total": total_settled,
        "settled_with_odds": len(covered),
        "settled_without_odds": len(missing),
        "coverage_pct": round(100 * len(covered) / total_settled, 2) if total_settled else None,
        "by_season": {str(k): v for k, v in sorted(by_season.items())},
    }


def _player_lineup_coverage(db: Session) -> dict[str, Any]:
    """Fraction of settled matches that have at least one PlayerLineup row."""
    try:
        from db.models.player_lineups import PlayerLineup
    except Exception as exc:
        return {"available": False, "reason": f"PlayerLineup model not importable: {exc}"}

    covered = {
        row.match_id
        for row in db.query(PlayerLineup.match_id).distinct().all()
    }
    settled_ids = {m.id for m in db.query(Match).filter(Match.result.isnot(None)).all()}
    total = len(settled_ids)
    return {
        "available": True,
        "settled_total": total,
        "settled_with_lineups": len(settled_ids & covered),
        "coverage_pct": round(100 * len(settled_ids & covered) / total, 2) if total else None,
    }


def _weather_coverage(db: Session) -> dict[str, Any]:
    try:
        from db.models.weather_snapshots import WeatherSnapshot
    except Exception as exc:
        return {"available": False, "reason": f"WeatherSnapshot model not importable: {exc}"}

    covered = {
        row.match_id
        for row in db.query(WeatherSnapshot.match_id).distinct().all()
    }
    settled_ids = {m.id for m in db.query(Match).filter(Match.result.isnot(None)).all()}
    total = len(settled_ids)
    return {
        "available": True,
        "settled_total": total,
        "settled_with_weather": len(settled_ids & covered),
        "coverage_pct": round(100 * len(settled_ids & covered) / total, 2) if total else None,
    }


def _upcoming_gaps(db: Session) -> dict[str, Any]:
    """Upcoming (unsettled) matches without odds — directly actionable."""
    upcoming = db.query(Match).filter(Match.result.is_(None)).all()
    covered_ids = {row.match_id for row in db.query(OddsSnapshot.match_id).distinct().all()}
    missing = [m for m in upcoming if m.id not in covered_ids]
    return {
        "upcoming_total": len(upcoming),
        "upcoming_without_odds": len(missing),
        "example_match_ids": [m.id for m in missing[:5]],
    }


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------

def _verdict(report: dict[str, Any]) -> tuple[str, list[str]]:
    warnings: list[str] = []
    odds_cov = report["odds"].get("coverage_pct") or 0
    if odds_cov < 50:
        warnings.append(
            f"Historical odds coverage is {odds_cov:.1f}% — blocks the strongest feature. "
            "Run backfill_squiggle_odds."
        )

    upcoming_gap = report["upcoming"].get("upcoming_without_odds", 0)
    if upcoming_gap > 0:
        warnings.append(f"{upcoming_gap} upcoming match(es) have no odds yet.")

    for src in ("player_lineups", "weather"):
        section = report.get(src, {})
        if section.get("available") and (section.get("coverage_pct") or 0) < 20:
            warnings.append(
                f"{src} coverage is {section['coverage_pct']:.1f}% — effectively unused."
            )

    if not warnings:
        return "ok", warnings
    if odds_cov < 10:
        return "critical", warnings
    return "warn", warnings


# ---------------------------------------------------------------------------
# Artifact writing
# ---------------------------------------------------------------------------

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
