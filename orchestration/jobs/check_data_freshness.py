"""
orchestration/jobs/check_data_freshness.py
-------------------------------------------
Job: Validate data freshness before running downstream jobs.

Checks:
  1. Age of the newest odds snapshot vs. settings.odds_freshness_hours
  2. Age of the newest AFL fixture record vs. settings.afl_freshness_hours
  3. Upcoming matches that have no odds snapshot at all

This is a SOFT job -- it logs warnings but does NOT raise, so the
orchestrator continues even if data is stale. The freshness metadata
is written to the daily summary artifact by generate_daily_summary.

Run order: first in the daily pipeline (before ingestion jobs).
"""

import time
from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger
from sqlalchemy.orm import Session

from config.settings import get_settings
from db.models.matches import Match
from db.models.odds_snapshots import OddsSnapshot
from db.session import db_session

settings = get_settings()
ACTIONABLE_LOOKAHEAD_DAYS = 7

# Module-level cache written by this job, read by generate_daily_summary.
# Reset to None at the start of each pipeline run.
_last_freshness_result: dict[str, Any] | None = None


def get_last_result() -> dict[str, Any] | None:
    """Return the freshness metadata from the most recent run() call."""
    return _last_freshness_result


def run() -> None:
    """
    Check odds and fixture data freshness.

    Populates module-level _last_freshness_result with:
      {
        "odds_age_hours": float | None,
        "odds_stale": bool,
        "afl_age_hours": float | None,
        "afl_stale": bool,
        "upcoming_without_odds": int,
        "upcoming_without_odds_all": int,
        "upcoming_without_odds_examples": [dict],
        "warnings": [str],
      }
    """
    global _last_freshness_result
    start = time.monotonic()
    logger.info("==> check_data_freshness: starting")

    _last_freshness_result = build_report()

    for warning in _last_freshness_result["warnings"]:
        logger.warning(warning)

    duration = time.monotonic() - start
    status = "WARNINGS FOUND" if _last_freshness_result["warnings"] else "OK"
    logger.info(f"==> check_data_freshness: {status} in {duration:.1f}s")


def build_report(now: datetime | None = None) -> dict[str, Any]:
    """Compute a fresh data-health snapshot directly from the database."""
    warnings: list[str] = []
    now = now or datetime.now(tz=timezone.utc)

    with db_session() as db:
        odds_age_hours = _odds_age_hours(db, now)
        afl_age_hours = _afl_age_hours(db, now)
        odds_gap = _upcoming_without_odds(db, now)

    odds_stale = False
    if odds_age_hours is None:
        warnings.append("No odds snapshots found -- odds have never been ingested.")
        odds_stale = True
    elif odds_age_hours > settings.odds_freshness_hours:
        warnings.append(
            f"Odds snapshots are stale: newest is {odds_age_hours:.1f}h old "
            f"(threshold {settings.odds_freshness_hours}h)."
        )
        odds_stale = True

    afl_stale = False
    if afl_age_hours is None:
        warnings.append("No AFL fixture data found -- AFL ingestion has never run.")
        afl_stale = True
    elif afl_age_hours > settings.afl_freshness_hours:
        warnings.append(
            f"AFL fixture data is stale: newest is {afl_age_hours:.1f}h old "
            f"(threshold {settings.afl_freshness_hours}h)."
        )
        afl_stale = True

    actionable_missing = odds_gap["actionable_count"]
    if actionable_missing > 0:
        warnings.append(
            f"{actionable_missing} upcoming match(es) in the next "
            f"{ACTIONABLE_LOOKAHEAD_DAYS}d have no odds snapshot."
        )

    return {
        "odds_age_hours": round(odds_age_hours, 2) if odds_age_hours is not None else None,
        "odds_stale": odds_stale,
        "afl_age_hours": round(afl_age_hours, 2) if afl_age_hours is not None else None,
        "afl_stale": afl_stale,
        "upcoming_without_odds": actionable_missing,
        "upcoming_without_odds_all": odds_gap["total_missing"],
        "upcoming_without_odds_examples": odds_gap["examples"],
        "warnings": warnings,
        "checked_at": now.isoformat(),
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _odds_age_hours(db: Session, now: datetime) -> float | None:
    """Return age in hours of the most recent odds snapshot, or None if none exist."""
    latest: OddsSnapshot | None = (
        db.query(OddsSnapshot)
        .order_by(OddsSnapshot.snapshot_time.desc())
        .first()
    )
    if latest is None:
        return None
    snap_at = latest.snapshot_time
    if snap_at.tzinfo is None:
        snap_at = snap_at.replace(tzinfo=timezone.utc)
    return (now - snap_at).total_seconds() / 3600


def _afl_age_hours(db: Session, now: datetime) -> float | None:
    """Return age in hours of the most recently updated AFL match record."""
    latest: Match | None = (
        db.query(Match)
        .order_by(Match.updated_at.desc())
        .first()
    )
    if latest is None:
        return None
    updated = latest.updated_at
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    return (now - updated).total_seconds() / 3600


def _upcoming_without_odds(db: Session, now: datetime) -> dict[str, Any]:
    """Return actionable and total upcoming matches that have no odds snapshot."""
    upcoming = db.query(Match).filter(Match.result == None).all()  # noqa: E711
    if not upcoming:
        return {"actionable_count": 0, "total_missing": 0, "examples": []}

    covered_ids = {row.match_id for row in db.query(OddsSnapshot.match_id).distinct().all()}
    missing = [match for match in upcoming if match.id not in covered_ids]

    actionable_cutoff = now + timedelta(days=ACTIONABLE_LOOKAHEAD_DAYS)
    actionable = [
        match for match in missing
        if match.match_time is not None
        and now <= _as_utc(match.match_time) <= actionable_cutoff
    ]

    examples = [
        {
            "match_id": match.id,
            "season": match.season,
            "round_number": match.round_number,
            "match_time": match.match_time.isoformat() if match.match_time else None,
            "home_team_id": match.home_team_id,
            "away_team_id": match.away_team_id,
        }
        for match in actionable[:5]
    ]
    return {
        "actionable_count": len(actionable),
        "total_missing": len(missing),
        "examples": examples,
    }


def _as_utc(value: datetime) -> datetime:
    """Normalize naive DB datetimes to UTC-aware values."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


if __name__ == "__main__":
    run()
    import json

    print(json.dumps(get_last_result(), indent=2))
