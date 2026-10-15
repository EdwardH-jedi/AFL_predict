"""
tests/test_bookmaker_extractor.py
----------------------------------
Unit tests for features/extractors/bookmaker.py.

Uses in-memory SQLite with a real ORM session. No network calls.
"""

from __future__ import annotations

import os

os.environ.setdefault("DB_URL", "sqlite:///:memory:")
os.environ.setdefault("ODDS_API_KEY", "")
os.environ.setdefault("SQUIGGLE_USER_AGENT", "test")

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.base import Base
from db.models.matches import Match
from db.models.odds_snapshots import OddsSnapshot
from db.models.teams import Team
from features.extractors.bookmaker import BookmakerExtractor

# ---------------------------------------------------------------------------
# Test DB fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def engine():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    import db.models  # noqa: F401 — register all models
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def db(engine):
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = SessionLocal()
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def team_pair(db):
    t1 = Team(name="Richmond", short_name="RICH", external_id="14")
    t2 = Team(name="Carlton", short_name="CAR", external_id="3")
    db.add_all([t1, t2])
    db.flush()
    return t1, t2


@pytest.fixture
def match_with_odds(db, team_pair):
    t1, t2 = team_pair
    mt = datetime(2025, 5, 1, 9, 30, tzinfo=UTC)

    m = Match(
        season=2025, round_number=5, round_label="Round 5",
        home_team_id=t1.id, away_team_id=t2.id,
        match_time=mt, is_final=False,
    )
    db.add(m)
    db.flush()

    # Snapshot 1 hour before match_time — valid pre-match odds
    snap = OddsSnapshot(
        match_id=m.id,
        bookmaker="tab",
        home_odds=1.75, away_odds=2.10,
        home_implied_prob=0.5432, away_implied_prob=0.4568,
        overround=1.043,
        snapshot_time=mt - timedelta(hours=1),
        snapshot_type="scheduled",
    )
    db.add(snap)
    db.flush()
    return m, snap


def _as_match(m: Match) -> SimpleNamespace:
    return SimpleNamespace(
        id=m.id, season=m.season, round_number=m.round_number,
        home_team_id=m.home_team_id, away_team_id=m.away_team_id,
        result=m.result, home_score=m.home_score, away_score=m.away_score,
        match_time=m.match_time, is_final=m.is_final, venue=m.venue,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBookmakerExtractor:
    def test_returns_null_features_for_no_odds(self, db, team_pair):
        t1, t2 = team_pair
        m = Match(
            season=2025, round_number=99, round_label="Round 99",
            home_team_id=t1.id, away_team_id=t2.id,
            match_time=datetime(2025, 9, 1, tzinfo=UTC),
            is_final=False,
        )
        db.add(m)
        db.flush()

        extractor = BookmakerExtractor(db)
        result = extractor.extract([_as_match(m)])
        row = result[m.id]
        assert row["bm_home_odds"] is None
        assert row["bm_home_implied_prob"] is None
        assert row["bm_overround"] is None

    def test_returns_correct_odds_when_present(self, db, match_with_odds):
        m, snap = match_with_odds
        extractor = BookmakerExtractor(db)
        result = extractor.extract([_as_match(m)])
        row = result[m.id]
        assert row["bm_home_odds"] == pytest.approx(1.75)
        assert row["bm_away_odds"] == pytest.approx(2.10)
        assert row["bm_home_implied_prob"] == pytest.approx(0.5432)
        assert row["bm_overround"] == pytest.approx(1.043)

    def test_snapshot_after_match_time_excluded(self, db, team_pair):
        t1, t2 = team_pair
        mt = datetime(2025, 6, 1, 10, 0, tzinfo=UTC)
        m = Match(
            season=2025, round_number=11, round_label="Round 11",
            home_team_id=t1.id, away_team_id=t2.id,
            match_time=mt, is_final=False,
        )
        db.add(m)
        db.flush()

        # Snapshot AFTER match start — must be excluded
        post_match_snap = OddsSnapshot(
            match_id=m.id, bookmaker="tab",
            home_odds=1.60, away_odds=2.30,
            home_implied_prob=0.59, away_implied_prob=0.41,
            overround=1.00,
            snapshot_time=mt + timedelta(hours=2),  # AFTER match_time
            snapshot_type="scheduled",
        )
        db.add(post_match_snap)
        db.flush()

        extractor = BookmakerExtractor(db)
        result = extractor.extract([_as_match(m)])
        # Post-match snapshot must not be used
        assert result[m.id]["bm_home_odds"] is None

    def test_latest_pre_match_snapshot_selected(self, db, team_pair):
        t1, t2 = team_pair
        mt = datetime(2025, 7, 1, 14, 0, tzinfo=UTC)
        m = Match(
            season=2025, round_number=15, round_label="Round 15",
            home_team_id=t1.id, away_team_id=t2.id,
            match_time=mt, is_final=False,
        )
        db.add(m)
        db.flush()

        # Older snapshot (2 days prior)
        snap_old = OddsSnapshot(
            match_id=m.id, bookmaker="tab",
            home_odds=1.90, away_odds=1.90,
            home_implied_prob=0.50, away_implied_prob=0.50,
            overround=1.05,
            snapshot_time=mt - timedelta(days=2),
            snapshot_type="scheduled",
        )
        # Newer snapshot (1 hour prior) — this should be selected
        snap_new = OddsSnapshot(
            match_id=m.id, bookmaker="tab",
            home_odds=1.75, away_odds=2.10,
            home_implied_prob=0.5432, away_implied_prob=0.4568,
            overround=1.043,
            snapshot_time=mt - timedelta(hours=1),
            snapshot_type="scheduled",
        )
        db.add_all([snap_old, snap_new])
        db.flush()

        extractor = BookmakerExtractor(db)
        result = extractor.extract([_as_match(m)])
        assert result[m.id]["bm_home_odds"] == pytest.approx(1.75)

    def test_match_without_match_time_returns_null(self, db, team_pair):
        t1, t2 = team_pair
        m = Match(
            season=2025, round_number=20, round_label="Round 20",
            home_team_id=t1.id, away_team_id=t2.id,
            match_time=None, is_final=False,
        )
        db.add(m)
        db.flush()

        extractor = BookmakerExtractor(db)
        result = extractor.extract([_as_match(m)])
        assert result[m.id]["bm_home_odds"] is None

    def test_all_required_keys_present(self, db, match_with_odds):
        m, _ = match_with_odds
        extractor = BookmakerExtractor(db)
        result = extractor.extract([_as_match(m)])
        row = result[m.id]
        for key in ["bm_home_odds", "bm_away_odds", "bm_home_implied_prob",
                    "bm_away_implied_prob", "bm_overround"]:
            assert key in row
