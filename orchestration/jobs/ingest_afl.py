"""
orchestration/jobs/ingest_afl.py
---------------------------------
Job: Fetch AFL fixtures and results from Squiggle and upsert into the database.

Pipeline per record:
    collect → parse → validate → transform → upsert

Idempotency strategy:
  - Teams:   upsert by external_id. Mutable fields (name, short_name) updated.
  - Matches: upsert by external_id. Scheduling fields updated; result written
             once and never overwritten (protects downstream bet outcomes).

Run daily at ~06:00 AEST. All rounds by default; use --round for one round.

CLI usage:
    python -m orchestration.jobs.ingest_afl --season 2025
    python -m orchestration.jobs.ingest_afl --season 2025 --round 5
"""

import argparse
import sys
import time
from datetime import UTC, date, datetime

from loguru import logger
from sqlalchemy.orm import Session

from collectors.afl_collector import AFLCollector
from collectors.parsers.squiggle_parser import ParsedGame, ParsedTeam
from collectors.transformers.afl_transformer import (
    game_to_match_kwargs,
    game_to_result_kwargs,
    game_to_schedule_kwargs,
    team_to_kwargs,
)
from collectors.validators.afl_validator import validate_game, validate_team
from config.settings import get_settings
from db.models.matches import Match
from db.models.pipeline_runs import PipelineRun
from db.models.teams import Team
from db.session import db_session

settings = get_settings()


def _current_season() -> int:
    """Return the current AFL season year (calendar year of today's date)."""
    return date.today().year


def run(season: int | None = None, round_number: int | None = None) -> None:
    """
    Fetch AFL teams + games for the given season/round and upsert into the DB.

    Args:
        season:       AFL season year. Defaults to the current calendar year.
        round_number: Optional round filter (None = all rounds).
    """
    if season is None:
        season = _current_season()
    start = time.monotonic()
    logger.info(f"==> ingest_afl: starting (season={season}, round={round_number})")

    with db_session() as db:
        run_record = PipelineRun(job_name="ingest_afl", status="running")
        db.add(run_record)
        db.flush()

        try:
            collector = AFLCollector()
            team_count = 0
            match_count = 0

            # ------------------------------------------------------------------
            # Phase 1: Teams
            # Upsert team reference data before matches (FK dependency).
            # ------------------------------------------------------------------
            parsed_teams = collector.fetch_teams()
            for team in parsed_teams:
                result = validate_team(team)
                if not result:
                    logger.warning(
                        f"ingest_afl: team {team.name!r} failed validation — "
                        f"skipping. {result.summary()}"
                    )
                    continue
                if result.warnings:
                    logger.debug(
                        f"ingest_afl: team {team.name!r} validation warnings: "
                        f"{result.warnings}"
                    )
                if _upsert_team(db, team):
                    team_count += 1

            db.flush()  # make team IDs available for match FK resolution

            # ------------------------------------------------------------------
            # Phase 2: Games (fixtures + results combined in one Squiggle call)
            # ------------------------------------------------------------------
            parsed_games = collector.fetch_games(season=season, round_number=round_number)
            for game in parsed_games:
                result = validate_game(game)
                if not result:
                    logger.warning(
                        f"ingest_afl: game {game.external_id} failed validation — "
                        f"skipping. {result.summary()}"
                    )
                    continue
                if result.warnings:
                    logger.debug(
                        f"ingest_afl: game {game.external_id} validation warnings: "
                        f"{result.warnings}"
                    )
                n = _upsert_game(db, game)
                match_count += n

            duration = time.monotonic() - start
            run_record.status = "completed"
            run_record.completed_at = datetime.now(tz=UTC)
            run_record.duration_seconds = round(duration, 2)
            run_record.records_processed = match_count
            logger.info(
                f"==> ingest_afl: completed in {duration:.1f}s — "
                f"{team_count} teams, {match_count}/{len(parsed_games)} matches upserted."
            )

        except Exception as exc:
            run_record.status = "failed"
            run_record.error_message = str(exc)
            logger.exception("==> ingest_afl: FAILED")
            raise


# ---------------------------------------------------------------------------
# Upsert helpers
# ---------------------------------------------------------------------------

def _upsert_team(db: Session, team: ParsedTeam) -> bool:
    """
    Insert or update a team by external_id, falling back to name lookup.

    Returns True if the row was inserted (not updated).
    """
    kwargs = team_to_kwargs(team)

    # Primary lookup: stable Squiggle team ID
    existing = db.query(Team).filter(Team.external_id == team.external_id).first()

    # Fallback: pre-existing seed data without external_id
    if existing is None:
        existing = db.query(Team).filter(Team.name == team.name).first()

    if existing is None:
        db.add(Team(**kwargs))
        db.flush()
        logger.debug(f"ingest_afl: inserted team {team.name!r} (ext={team.external_id})")
        return True

    # Update all mutable fields — catches upstream name/abbreviation corrections
    for key, val in kwargs.items():
        if key == "external_id" and existing.external_id is not None:
            continue  # never overwrite a set external_id with a different value
        setattr(existing, key, val)
    return False


def _upsert_game(db: Session, game: ParsedGame) -> int:
    """
    Insert or update a match record.

    Returns 1 if a row was inserted or a result/schedule was changed, else 0.
    """
    home_team = _resolve_team(db, game.home_team_name, game.home_team_external_id)
    away_team = _resolve_team(db, game.away_team_name, game.away_team_external_id)

    if home_team is None or away_team is None:
        logger.warning(
            f"ingest_afl: cannot resolve teams for game {game.external_id} "
            f"({game.home_team_name} vs {game.away_team_name}) — skipping."
        )
        return 0

    existing: Match | None = (
        db.query(Match).filter(Match.external_id == game.external_id).first()
    )

    if existing is None:
        # Build full kwargs via transformer and insert
        kwargs = game_to_match_kwargs(game, home_team.id, away_team.id)
        db.add(Match(**kwargs))
        db.flush()
        logger.debug(
            f"ingest_afl: inserted match {game.external_id} "
            f"({game.home_team_name} vs {game.away_team_name} "
            f"S{game.season}R{game.round_number})"
        )
        return 1

    # --- Update existing row ---
    changed = False

    # Scheduling fields may be corrected by Squiggle (reschedule, venue change)
    schedule_kwargs = game_to_schedule_kwargs(game)
    for key, val in schedule_kwargs.items():
        existing_val = getattr(existing, key)
        # Normalize datetime comparison: SQLite returns naive datetimes, strip tz
        # for comparison purposes (all datetimes are UTC).
        if isinstance(val, datetime) and isinstance(existing_val, datetime):
            cmp_val = val.replace(tzinfo=None)
            cmp_existing = existing_val.replace(tzinfo=None)
        else:
            cmp_val, cmp_existing = val, existing_val
        if cmp_existing != cmp_val:
            setattr(existing, key, val)
            changed = True

    # Settle result ONLY if not already written (protect downstream bet outcomes)
    newly_settled = False
    if game.is_complete and existing.result is None:
        result_kwargs = game_to_result_kwargs(game)
        if result_kwargs:
            for key, val in result_kwargs.items():
                setattr(existing, key, val)
            newly_settled = True
            logger.info(
                f"ingest_afl: settled match {game.external_id} "
                f"result={game.result} ({game.home_score}–{game.away_score})"
            )

    return 1 if (changed or newly_settled) else 0


def _resolve_team(db: Session, name: str, external_id: str) -> Team | None:
    """
    Look up a team by external_id, falling back to name.
    Returns None if the team is not in the DB.
    """
    team = db.query(Team).filter(Team.external_id == external_id).first()
    if team:
        return team
    team = db.query(Team).filter(Team.name == name).first()
    if team:
        return team
    logger.warning(
        f"ingest_afl: team not found — name={name!r} ext={external_id!r}. "
        "Ensure teams are ingested before matches."
    )
    return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    _season = _current_season()
    p = argparse.ArgumentParser(
        description="Ingest AFL fixtures and results from Squiggle API."
    )
    p.add_argument(
        "--season", type=int, default=_season,
        help=f"AFL season year (default: {_season})"
    )
    p.add_argument(
        "--round", dest="round_number", type=int, default=None,
        help="Restrict to a specific round number (optional)"
    )
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    try:
        run(season=args.season, round_number=args.round_number)
    except Exception:
        sys.exit(1)
