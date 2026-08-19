"""
tests/test_ingest_afl.py
-------------------------
Integration tests for orchestration/jobs/ingest_afl.py.

Uses in-memory SQLite (via conftest.py). No network calls —
the AFLCollector is monkeypatched to return synthetic data.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from collectors.parsers.squiggle_parser import ParsedGame, ParsedTeam
from db.models.matches import Match
from db.models.teams import Team
from orchestration.jobs.ingest_afl import (
    _upsert_game,
    _upsert_team,
    run,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _team(name="Richmond", ext_id="14", short="RICH", state="VIC") -> ParsedTeam:
    return ParsedTeam(external_id=ext_id, name=name, short_name=short, state=state)


def _game(
    ext_id="1001",
    season=2025,
    round_number=1,
    home_name="Richmond",
    home_ext_id="14",
    away_name="Carlton",
    away_ext_id="3",
    match_time=None,
    is_complete=False,
    result=None,
    home_score=None,
    away_score=None,
) -> ParsedGame:
    return ParsedGame(
        external_id=ext_id,
        season=season,
        round_number=round_number,
        round_label=f"Round {round_number}",
        home_team_name=home_name,
        away_team_name=away_name,
        home_team_external_id=home_ext_id,
        away_team_external_id=away_ext_id,
        match_time=match_time or datetime(2025, 3, 20, 8, 30, tzinfo=UTC),
        venue="MCG",
        home_score=home_score,
        away_score=away_score,
        result=result,
        is_complete=is_complete,
        is_final=False,
    )


def _seed_teams(db):
    """Insert Richmond and Carlton into the DB."""
    _upsert_team(db, _team("Richmond", "14"))
    _upsert_team(db, _team("Carlton", "3", short="CARL", state="VIC"))
    db.flush()


# ---------------------------------------------------------------------------
# _upsert_team
# ---------------------------------------------------------------------------

class TestUpsertTeam:
    def test_inserts_new_team(self, db_session):
        _upsert_team(db_session, _team())
        db_session.flush()
        team = db_session.query(Team).filter(Team.name == "Richmond").first()
        assert team is not None
        assert team.external_id == "14"
        assert team.short_name == "RICH"

    def test_is_idempotent_on_second_call(self, db_session):
        _upsert_team(db_session, _team())
        _upsert_team(db_session, _team())  # second call — no duplicate
        db_session.flush()
        count = db_session.query(Team).filter(Team.name == "Richmond").count()
        assert count == 1

    def test_updates_short_name_on_re_insert(self, db_session):
        _upsert_team(db_session, _team())
        db_session.flush()
        updated = _team(short="RIC")
        _upsert_team(db_session, updated)
        db_session.flush()
        team = db_session.query(Team).filter(Team.external_id == "14").first()
        assert team.short_name == "RIC"

    def test_matches_existing_team_by_name_when_no_external_id(self, db_session):
        """Team seeded without external_id should be found by name and updated."""
        existing = Team(name="Richmond", short_name="RICH", external_id=None)
        db_session.add(existing)
        db_session.flush()
        _upsert_team(db_session, _team())  # has external_id="14"
        db_session.flush()
        team = db_session.query(Team).filter(Team.name == "Richmond").first()
        assert team.external_id == "14"


# ---------------------------------------------------------------------------
# _upsert_game
# ---------------------------------------------------------------------------

class TestUpsertGame:
    def test_inserts_new_fixture(self, db_session):
        _seed_teams(db_session)
        n = _upsert_game(db_session, _game())
        db_session.flush()
        assert n == 1
        match = db_session.query(Match).filter(Match.external_id == "1001").first()
        assert match is not None
        assert match.season == 2025
        assert match.result is None

    def test_is_idempotent_on_second_insert(self, db_session):
        _seed_teams(db_session)
        _upsert_game(db_session, _game())
        db_session.flush()
        n = _upsert_game(db_session, _game())  # same game, no changes
        db_session.flush()
        count = db_session.query(Match).filter(Match.external_id == "1001").count()
        assert count == 1
        assert n == 0  # no change

    def test_settles_result_when_complete(self, db_session):
        _seed_teams(db_session)
        # Insert as fixture (incomplete)
        _upsert_game(db_session, _game())
        db_session.flush()
        # Now settle it
        settled = _game(is_complete=True, result="home", home_score=102, away_score=89)
        n = _upsert_game(db_session, settled)
        db_session.flush()
        match = db_session.query(Match).filter(Match.external_id == "1001").first()
        assert match.result == "home"
        assert match.home_score == 102
        assert n == 1

    def test_does_not_overwrite_existing_result(self, db_session):
        """Once settled, result must not be overwritten (protect downstream bets)."""
        _seed_teams(db_session)
        settled = _game(is_complete=True, result="home", home_score=102, away_score=89)
        _upsert_game(db_session, settled)
        db_session.flush()
        # Attempt to re-settle with different result (should not change)
        re_settled = _game(is_complete=True, result="away", home_score=80, away_score=100)
        _upsert_game(db_session, re_settled)
        db_session.flush()
        match = db_session.query(Match).filter(Match.external_id == "1001").first()
        assert match.result == "home"  # unchanged

    def test_skips_game_with_unknown_teams(self, db_session):
        """Game whose teams are not in DB should return 0 (skipped)."""
        # No team seed
        n = _upsert_game(db_session, _game())
        assert n == 0

    def test_updates_venue_on_change(self, db_session):
        _seed_teams(db_session)
        _upsert_game(db_session, _game())
        db_session.flush()
        # Simulate Squiggle correcting venue
        updated = _game()
        updated.venue = "Docklands"
        _upsert_game(db_session, updated)
        db_session.flush()
        match = db_session.query(Match).filter(Match.external_id == "1001").first()
        assert match.venue == "Docklands"


# ---------------------------------------------------------------------------
# run() — end-to-end with mocked collector
# ---------------------------------------------------------------------------

class TestRunJob:
    def test_run_inserts_teams_and_games(self, db_session):
        """run() with mocked collector inserts teams and fixtures."""
        mock_collector = MagicMock()
        mock_collector.fetch_teams.return_value = [
            _team("Richmond", "14"),
            _team("Carlton", "3", short="CARL"),
        ]
        mock_collector.fetch_games.return_value = [_game()]

        with (
            patch("orchestration.jobs.ingest_afl.AFLCollector", return_value=mock_collector),
            patch("orchestration.jobs.ingest_afl.db_session") as mock_db_ctx,
        ):
            mock_db_ctx.return_value.__enter__ = lambda s: db_session
            mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)
            run(season=2025)

        matches = db_session.query(Match).all()
        teams = db_session.query(Team).all()
        assert len(matches) == 1
        assert len(teams) == 2

    def test_run_handles_collector_failure_gracefully(self, db_session):
        """run() should not silently swallow exceptions."""
        mock_collector = MagicMock()
        mock_collector.fetch_teams.side_effect = RuntimeError("network error")

        with (
            patch("orchestration.jobs.ingest_afl.AFLCollector", return_value=mock_collector),
            patch("orchestration.jobs.ingest_afl.db_session") as mock_db_ctx,
        ):
            mock_db_ctx.return_value.__enter__ = lambda s: db_session
            mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)
            with pytest.raises(RuntimeError, match="network error"):
                run(season=2025)
