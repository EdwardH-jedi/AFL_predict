"""
tests/test_ingest_tab_odds.py
------------------------------
Integration tests for orchestration/jobs/ingest_tab_odds.py.

Uses in-memory SQLite (via conftest.py). No network calls —
TABOddsCollector is monkeypatched to return synthetic data.
"""

from datetime import UTC, datetime

from collectors.parsers.odds_parser import ParsedOddsEvent
from db.models.matches import Match
from db.models.odds_snapshots import OddsSnapshot
from db.models.teams import Team
from orchestration.jobs.ingest_tab_odds import _resolve_match, _upsert_odds_snapshot

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2025, 3, 20, 8, 0, 0, tzinfo=UTC)


def _seed_match(db, home_name="Richmond", away_name="Carlton", result=None) -> Match:
    """Insert teams and a match, return the Match."""
    home = Team(name=home_name, short_name=home_name[:4].upper(), external_id=f"ext_{home_name}")
    away = Team(name=away_name, short_name=away_name[:4].upper(), external_id=f"ext_{away_name}")
    db.add_all([home, away])
    db.flush()
    match = Match(
        season=2025,
        round_number=1,
        round_label="Round 1",
        home_team_id=home.id,
        away_team_id=away.id,
        match_time=datetime(2025, 3, 20, 9, 30, tzinfo=UTC),
        venue="MCG",
        external_id="squiggle-1001",
        result=result,
    )
    db.add(match)
    db.flush()
    return match


def _odds_event(
    home_name="Richmond",
    away_name="Carlton",
    home_odds=1.75,
    away_odds=2.10,
    bookmaker_key="tab",
) -> ParsedOddsEvent:
    return ParsedOddsEvent(
        external_event_id="odds-event-abc",
        home_team_name=home_name,
        away_team_name=away_name,
        commence_time=datetime(2025, 3, 20, 8, 30, tzinfo=UTC),
        bookmaker_key=bookmaker_key,
        bookmaker_title=bookmaker_key.upper(),
        home_odds=home_odds,
        away_odds=away_odds,
        odds_last_update=_NOW,
    )


# ---------------------------------------------------------------------------
# _resolve_match
# ---------------------------------------------------------------------------

class TestResolveMatch:
    def test_finds_unsettled_match(self, db_session):
        _seed_match(db_session)
        match = _resolve_match(db_session, "Richmond", "Carlton")
        assert match is not None

    def test_returns_none_when_team_missing(self, db_session):
        # No teams seeded
        match = _resolve_match(db_session, "Richmond", "Carlton")
        assert match is None

    def test_returns_none_for_settled_match(self, db_session):
        """Settled match (result != None) should not be returned for new odds."""
        _seed_match(db_session, result="home")
        match = _resolve_match(db_session, "Richmond", "Carlton")
        assert match is None

    def test_returns_none_when_home_away_swapped(self, db_session):
        """Swapped home/away should not match (different game)."""
        _seed_match(db_session)
        match = _resolve_match(db_session, "Carlton", "Richmond")
        assert match is None


# ---------------------------------------------------------------------------
# _upsert_odds_snapshot
# ---------------------------------------------------------------------------

class TestUpsertOddsSnapshot:
    def test_inserts_new_snapshot(self, db_session):
        match = _seed_match(db_session)
        event = _odds_event()
        n = _upsert_odds_snapshot(db_session, event, _NOW)
        db_session.flush()
        assert n == 1
        snap = db_session.query(OddsSnapshot).filter(OddsSnapshot.match_id == match.id).first()
        assert snap is not None
        assert snap.home_odds == 1.75
        assert snap.away_odds == 2.10
        assert snap.bookmaker == "tab"

    def test_computes_implied_probabilities(self, db_session):
        _seed_match(db_session)
        _upsert_odds_snapshot(db_session, _odds_event(), _NOW)
        db_session.flush()
        snap = db_session.query(OddsSnapshot).first()
        assert snap.home_implied_prob is not None
        assert snap.away_implied_prob is not None
        assert snap.overround is not None
        # Probs should sum to ~1.0
        assert abs(snap.home_implied_prob + snap.away_implied_prob - 1.0) < 0.001

    def test_idempotent_on_second_call_same_day(self, db_session):
        """Second upsert on same day should update in-place, not insert duplicate."""
        _seed_match(db_session)
        _upsert_odds_snapshot(db_session, _odds_event(), _NOW)
        db_session.flush()
        # Call again with updated odds
        updated_event = _odds_event(home_odds=1.80, away_odds=2.05)
        _upsert_odds_snapshot(db_session, updated_event, _NOW)
        db_session.flush()
        count = db_session.query(OddsSnapshot).count()
        assert count == 1  # no duplicate
        snap = db_session.query(OddsSnapshot).first()
        assert snap.home_odds == 1.80  # updated

    def test_inserts_new_snapshot_on_different_day(self, db_session):
        """Snapshots on different calendar days are distinct records."""
        _seed_match(db_session)
        day1 = datetime(2025, 3, 19, 8, 0, tzinfo=UTC)
        day2 = datetime(2025, 3, 20, 8, 0, tzinfo=UTC)
        _upsert_odds_snapshot(db_session, _odds_event(), day1)
        db_session.flush()
        _upsert_odds_snapshot(db_session, _odds_event(), day2)
        db_session.flush()
        count = db_session.query(OddsSnapshot).count()
        assert count == 2

    def test_skips_when_no_match_in_db(self, db_session):
        """No match in DB → returns 0 (skipped)."""
        event = _odds_event()
        n = _upsert_odds_snapshot(db_session, event, _NOW)
        assert n == 0

    def test_skips_invalid_odds(self, db_session):
        """Odds that fail compute_implied_probs should not insert."""
        _seed_match(db_session)
        bad_event = _odds_event(home_odds=0.5, away_odds=2.10)  # invalid
        n = _upsert_odds_snapshot(db_session, bad_event, _NOW)
        assert n == 0
        assert db_session.query(OddsSnapshot).count() == 0

    def test_normalises_team_names(self, db_session):
        """Odds API names like 'Richmond Tigers' should be normalised to 'Richmond'."""
        _seed_match(db_session)  # seeded as "Richmond" and "Carlton"
        # Odds event with long-form names (as The Odds API might return)
        event = _odds_event(home_name="Richmond Tigers", away_name="Carlton Blues")
        n = _upsert_odds_snapshot(db_session, event, _NOW)
        db_session.flush()
        assert n == 1  # normalisation succeeded

    def test_separate_bookmakers_create_separate_snapshots(self, db_session):
        """Different bookmakers for the same match on the same day = separate rows."""
        _seed_match(db_session)
        tab_event = _odds_event(bookmaker_key="tab")
        sportsbet_event = _odds_event(bookmaker_key="sportsbet")
        _upsert_odds_snapshot(db_session, tab_event, _NOW)
        _upsert_odds_snapshot(db_session, sportsbet_event, _NOW)
        db_session.flush()
        count = db_session.query(OddsSnapshot).count()
        assert count == 2
