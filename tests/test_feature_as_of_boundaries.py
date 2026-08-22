"""
tests/test_feature_as_of_boundaries.py
---------------------------------------
Adversarial coverage for feature-level as-of boundaries (§5).

Temporal fold separation is enforced by backtesting/splits.py and was never in
doubt. What was overstated is the step below it: two extractors admitted data
whose availability before kickoff could not be established.

  weather               queried on match_id alone, ignoring `fetched_at`. The
                        collector fetches *observed* conditions, so a row
                        captured after the match carries the actual match-day
                        weather.
  player_availability   admitted rows with a NULL `announced_at` on the grounds
                        that historical data has no timestamp — fail-open. Those
                        rows are derived from who actually played.

Both are now fail-closed: a feature value is used only if it demonstrably
existed before kickoff, with an explicit opt-in for retrospective analysis.

Neither change moves a published number — both families are constant across the
canonical dataset (weather measurements null, availability 1.0 everywhere) — so
this is about the guarantee being true, not about the metrics.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from db.models.matches import Match
from db.models.player_lineups import PlayerLineup
from db.models.weather_snapshots import WeatherSnapshot
from features.extractors.player_availability import PlayerAvailabilityExtractor
from features.extractors.weather import WeatherExtractor

KICKOFF = datetime(2025, 6, 1, 14, 0)


def _match(db, **kw) -> Match:
    m = Match(season=2025, round_number=5, home_team_id=1, away_team_id=2,
              match_time=KICKOFF, **kw)
    db.add(m)
    db.flush()
    return m


def _weather(db, match_id, fetched_at, temp=18.0):
    db.add(WeatherSnapshot(
        match_id=match_id, venue_name="MCG", temperature_c=temp,
        wind_speed_kmh=10.0, precipitation_mm=0.0, fetched_at=fetched_at,
    ))
    db.flush()


# ---------------------------------------------------------------------------
# Weather
# ---------------------------------------------------------------------------

def test_weather_captured_before_kickoff_is_used(db_session):
    m = _match(db_session)
    _weather(db_session, m.id, fetched_at=KICKOFF - timedelta(hours=3))
    out = WeatherExtractor(db_session).extract([m])[m.id]
    assert out["weather_temp_c"] == pytest.approx(18.0)


def test_weather_captured_after_kickoff_is_excluded(db_session):
    """The leakage case: observed conditions fetched post-match."""
    m = _match(db_session)
    _weather(db_session, m.id, fetched_at=KICKOFF + timedelta(hours=4))
    out = WeatherExtractor(db_session).extract([m])[m.id]
    assert out["weather_temp_c"] is None, "post-kickoff weather leaked into features"


def test_weather_captured_exactly_at_kickoff_is_excluded(db_session):
    """Boundary is strict: available *before* the match, not at it."""
    m = _match(db_session)
    _weather(db_session, m.id, fetched_at=KICKOFF)
    assert WeatherExtractor(db_session).extract([m])[m.id]["weather_temp_c"] is None


def test_weather_with_unknown_capture_time_is_excluded(db_session):
    """Unknown provenance is treated as unavailable, not as safe."""
    m = _match(db_session)
    _weather(db_session, m.id, fetched_at=None)
    assert WeatherExtractor(db_session).extract([m])[m.id]["weather_temp_c"] is None


def test_weather_retrospective_opt_in_admits_late_rows(db_session):
    """The escape hatch exists, is off by default, and is explicit."""
    m = _match(db_session)
    _weather(db_session, m.id, fetched_at=KICKOFF + timedelta(hours=4))
    out = WeatherExtractor(db_session, allow_retrospective=True).extract([m])[m.id]
    assert out["weather_temp_c"] == pytest.approx(18.0)


def test_weather_excluded_rows_are_counted(db_session):
    m = _match(db_session)
    _weather(db_session, m.id, fetched_at=KICKOFF + timedelta(hours=1))
    ex = WeatherExtractor(db_session)
    ex.extract([m])
    assert ex._excluded_not_as_of == 1


# ---------------------------------------------------------------------------
# Player availability
# ---------------------------------------------------------------------------

def _lineup(db, match_id, team_id, announced_at):
    db.add(PlayerLineup(
        match_id=match_id, team_id=team_id, announced_at=announced_at,
        availability_index=0.8, key_players_absent=2,
    ))
    db.flush()


def test_lineup_announced_before_kickoff_is_used(db_session):
    m = _match(db_session)
    _lineup(db_session, m.id, 1, KICKOFF - timedelta(days=1))
    _lineup(db_session, m.id, 2, KICKOFF - timedelta(days=1))
    out = PlayerAvailabilityExtractor(db_session).extract([m])[m.id]
    assert out["home_availability_index"] == pytest.approx(0.8)


def test_lineup_announced_after_kickoff_is_excluded(db_session):
    """The real lineup value must not reach the features.

    Exclusion falls back to the extractor's neutral default (1.0), not to a
    missing marker — see test_excluded_data_is_indistinguishable_from_available.
    """
    m = _match(db_session)
    _lineup(db_session, m.id, 1, KICKOFF + timedelta(hours=2))
    _lineup(db_session, m.id, 2, KICKOFF + timedelta(hours=2))
    out = PlayerAvailabilityExtractor(db_session).extract([m])[m.id]
    assert out["home_availability_index"] != pytest.approx(0.8)
    assert out["home_key_players_absent"] != 2


def test_null_announcement_time_is_excluded_by_default(db_session):
    """Was fail-open: NULL meant 'historical, therefore safe'."""
    m = _match(db_session)
    _lineup(db_session, m.id, 1, None)
    _lineup(db_session, m.id, 2, None)
    out = PlayerAvailabilityExtractor(db_session).extract([m])[m.id]
    assert out["home_availability_index"] != pytest.approx(0.8), (
        "a lineup with unknown announcement time was admitted as pre-match"
    )
    assert out["home_key_players_absent"] != 2


def test_null_announcement_opt_in_admits_historical_rows(db_session):
    m = _match(db_session)
    _lineup(db_session, m.id, 1, None)
    _lineup(db_session, m.id, 2, None)
    out = PlayerAvailabilityExtractor(
        db_session, allow_unknown_announcement=True
    ).extract([m])[m.id]
    assert out["home_availability_index"] == pytest.approx(0.8)


def test_missing_kickoff_time_excludes_the_lineup(db_session):
    """With no kickoff the boundary cannot be evaluated, so nothing is admitted."""
    m = _match(db_session)
    m.match_time = None
    db_session.flush()
    _lineup(db_session, m.id, 1, KICKOFF - timedelta(days=1))
    out = PlayerAvailabilityExtractor(db_session).extract([m])[m.id]
    assert out["home_availability_index"] != pytest.approx(0.8)


def test_excluded_data_is_indistinguishable_from_available(db_session):
    """A documented weakness of the current encoding, pinned so it is not forgotten.

    Excluding a lineup falls back to availability 1.0 / zero absences — the same
    values a fully-available team would produce. The extractor cannot express
    "unknown" separately from "everyone fit", so fail-closed here means
    "assume nothing is wrong" rather than "mark as missing".

    That is safe for leakage (no post-match information enters) but it is not a
    neutral imputation, and it is one reason the availability family carries no
    signal across the canonical dataset. Fixing it means a nullable encoding and
    a model change, which is out of scope for this pass.
    """
    late = _match(db_session)
    _lineup(db_session, late.id, 1, KICKOFF + timedelta(hours=2))
    _lineup(db_session, late.id, 2, KICKOFF + timedelta(hours=2))
    excluded = PlayerAvailabilityExtractor(db_session).extract([late])[late.id]

    bare = _match(db_session)          # no lineup rows at all
    absent = PlayerAvailabilityExtractor(db_session).extract([bare])[bare.id]

    assert excluded == absent, "excluded and never-present should currently coincide"
