"""
orchestration/jobs/ingest_tab_odds.py
--------------------------------------
Job: Fetch TAB/AU H2H odds snapshots for upcoming AFL matches and store them.

Pipeline per record:
    collect → parse → validate → transform → upsert

Idempotency strategy:
  - At most one snapshot per (match_id, bookmaker_key, UTC calendar date).
  - Same-day duplicate → update in-place (odds may have shifted).
  - Different day → insert new row (preserves history).

Match resolution:
  - Team names from the odds feed are normalised before DB lookup.
  - If no unsettled match is found, the event is skipped with a warning.
    Always run ingest_afl before ingest_tab_odds.

CLI usage:
    python -m orchestration.jobs.ingest_tab_odds
    python -m orchestration.jobs.ingest_tab_odds --dry-run
    python -m orchestration.jobs.ingest_tab_odds --snapshot-only
"""

import argparse
import sys
import time
from datetime import UTC, datetime

from loguru import logger
from sqlalchemy import func
from sqlalchemy.orm import Session

from collectors.parsers.odds_parser import ParsedOddsEvent
from collectors.tab_odds_collector import TABOddsCollector
from collectors.team_normalizer import get_unknown_aliases, normalize, reset_unknown
from collectors.transformers.odds_transformer import (
    odds_event_to_snapshot_kwargs,
    odds_event_to_update_kwargs,
)
from collectors.validators.odds_validator import validate_odds_event
from config.settings import get_settings
from db.models.matches import Match
from db.models.odds_snapshots import OddsSnapshot
from db.models.pipeline_runs import PipelineRun
from db.models.teams import Team
from db.session import db_session

settings = get_settings()


def run(dry_run: bool = False, snapshot_only: bool = False) -> None:
    """
    Fetch H2H odds and upsert snapshots into the database.

    Args:
        dry_run:       Parse + validate + log; do not write to DB.
        snapshot_only: Fetch + save raw snapshot to disk; skip parse/DB entirely.
                       Useful for capturing a payload to replay later.
    """
    start = time.monotonic()
    logger.info(
        f"==> ingest_tab_odds: starting "
        f"(dry_run={dry_run}, snapshot_only={snapshot_only})"
    )
    reset_unknown()  # clear alias tracking from any previous run

    with db_session() as db:
        run_record = PipelineRun(job_name="ingest_tab_odds", status="running")
        db.add(run_record)
        db.flush()

        try:
            collector = TABOddsCollector()

            if snapshot_only:
                # Just fetch and save the raw snapshot — no parsing or DB writes.
                collector.fetch_upcoming_h2h()
                logger.info("==> ingest_tab_odds: snapshot saved, exiting (snapshot_only=True).")
                run_record.status = "completed"
                run_record.completed_at = datetime.now(tz=UTC)
                run_record.duration_seconds = round(time.monotonic() - start, 2)
                return

            events = collector.fetch_upcoming_h2h()
            snapshot_time = datetime.now(tz=UTC)
            records_written = 0
            records_skipped = 0

            for event in events:
                # --- Validate ---
                result = validate_odds_event(event)
                if not result:
                    logger.warning(
                        f"ingest_tab_odds: event {event.external_event_id} "
                        f"failed validation — skipping. {result.summary()}"
                    )
                    records_skipped += 1
                    continue
                if result.warnings:
                    logger.debug(
                        f"ingest_tab_odds: event {event.external_event_id} "
                        f"validation warnings: {result.warnings}"
                    )

                if dry_run:
                    canonical_home = normalize(event.home_team_name)
                    canonical_away = normalize(event.away_team_name)
                    logger.info(
                        f"[DRY RUN] {canonical_home} {event.home_odds} / "
                        f"{canonical_away} {event.away_odds} "
                        f"[{event.bookmaker_title}]"
                    )
                    records_written += 1
                    continue

                # --- Transform + Upsert ---
                n = _upsert_odds_snapshot(db, event, snapshot_time)
                records_written += n
                if n == 0:
                    records_skipped += 1

            unknown = get_unknown_aliases()
            if unknown:
                logger.warning(
                    f"ingest_tab_odds: {len(unknown)} unrecognised team name(s) — "
                    f"add to collectors/team_normalizer.py ALIASES: {sorted(unknown)}"
                )

            duration = time.monotonic() - start
            run_record.status = "completed"
            run_record.completed_at = datetime.now(tz=UTC)
            run_record.duration_seconds = round(duration, 2)
            run_record.records_processed = records_written
            logger.info(
                f"==> ingest_tab_odds: completed in {duration:.1f}s — "
                f"{records_written} written, {records_skipped} skipped "
                f"(of {len(events)} events)."
            )

        except Exception as exc:
            run_record.status = "failed"
            run_record.error_message = str(exc)
            logger.exception("==> ingest_tab_odds: FAILED")
            raise


# ---------------------------------------------------------------------------
# Upsert helpers
# ---------------------------------------------------------------------------

def _upsert_odds_snapshot(
    db: Session,
    event: ParsedOddsEvent,
    snapshot_time: datetime,
) -> int:
    """
    Insert or update an odds snapshot for one event.

    Returns 1 if the snapshot was written (insert or update), 0 if skipped.
    """
    canonical_home = normalize(event.home_team_name)
    canonical_away = normalize(event.away_team_name)

    match = _resolve_match(db, canonical_home, canonical_away)
    if match is None:
        logger.warning(
            f"ingest_tab_odds: no DB match for "
            f"{event.home_team_name!r} vs {event.away_team_name!r} "
            f"(normalised: {canonical_home!r} vs {canonical_away!r}). "
            "Run ingest_afl first to load fixtures."
        )
        return 0

    today = snapshot_time.date()

    # Idempotency: one snapshot per (match, bookmaker, calendar day)
    existing: OddsSnapshot | None = (
        db.query(OddsSnapshot)
        .filter(OddsSnapshot.match_id == match.id)
        .filter(OddsSnapshot.bookmaker == event.bookmaker_key)
        .filter(func.date(OddsSnapshot.snapshot_time) == str(today))
        .first()
    )

    if existing is not None:
        # Update in-place — use transformer to get the update kwargs
        update_kwargs = odds_event_to_update_kwargs(event, snapshot_time)
        for key, val in update_kwargs.items():
            setattr(existing, key, val)
        logger.debug(
            f"ingest_tab_odds: updated snapshot match={match.id} "
            f"[{event.bookmaker_key}] home={event.home_odds} away={event.away_odds}"
        )
    else:
        # Insert new snapshot — use transformer to build full kwargs
        try:
            snapshot_kwargs = odds_event_to_snapshot_kwargs(event, match.id, snapshot_time)
        except ValueError as exc:
            logger.warning(
                f"ingest_tab_odds: skipping snapshot match={match.id} "
                f"[{event.bookmaker_key}] — invalid odds: {exc}"
            )
            return 0
        db.add(OddsSnapshot(**snapshot_kwargs))
        logger.debug(
            f"ingest_tab_odds: inserted snapshot match={match.id} "
            f"[{event.bookmaker_key}] home={event.home_odds} away={event.away_odds}"
        )

    return 1


def _resolve_match(
    db: Session, home_team_name: str, away_team_name: str
) -> Match | None:
    """
    Find the nearest upcoming unsettled match for the given canonical team pair.

    Returns None if no match is found (teams unknown, or no upcoming fixture).
    """
    home_team = db.query(Team).filter(Team.name == home_team_name).first()
    away_team = db.query(Team).filter(Team.name == away_team_name).first()

    if home_team is None or away_team is None:
        return None

    return (
        db.query(Match)
        .filter(Match.home_team_id == home_team.id)
        .filter(Match.away_team_id == away_team.id)
        .filter(Match.result.is_(None))
        .order_by(Match.match_time.asc())
        .first()
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Ingest TAB/AU H2H odds snapshots for upcoming AFL matches."
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Parse + validate + log odds without writing to the database."
    )
    p.add_argument(
        "--snapshot-only", action="store_true",
        help="Fetch and save raw snapshot to disk only; skip parsing and DB writes."
    )
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    try:
        run(dry_run=args.dry_run, snapshot_only=args.snapshot_only)
    except Exception:
        sys.exit(1)
