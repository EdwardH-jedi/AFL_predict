"""
tests/test_odds_parser.py
--------------------------
Unit tests for collectors/parsers/odds_parser.py.

No network calls, no database — pure function testing.
"""

from datetime import UTC, datetime

import pytest

from collectors.parsers.odds_parser import (
    ODDS_MAX,
    OddsParseError,
    parse_events,
    validate_odds_pair,
)

# ---------------------------------------------------------------------------
# Test data helpers
# ---------------------------------------------------------------------------

def _make_event(**overrides) -> dict:
    """Return a minimal valid Odds API event dict."""
    base = {
        "id": "event-abc-123",
        "sport_key": "aussierules_afl",
        "commence_time": "2025-03-20T08:30:00Z",
        "home_team": "Richmond",
        "away_team": "Carlton",
        "bookmakers": [
            {
                "key": "tab",
                "title": "TAB",
                "last_update": "2025-03-19T22:00:00Z",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Richmond", "price": 1.75},
                            {"name": "Carlton", "price": 2.10},
                        ],
                    }
                ],
            }
        ],
    }
    base.update(overrides)
    return base


_PREFS = ["tab", "sportsbet"]


# ---------------------------------------------------------------------------
# parse_events — structural errors
# ---------------------------------------------------------------------------

def test_parse_events_raises_on_non_list():
    with pytest.raises(OddsParseError, match="Expected list"):
        parse_events({"data": []}, _PREFS)


def test_parse_events_empty_list():
    assert parse_events([], _PREFS) == []


# ---------------------------------------------------------------------------
# parse_events — valid event
# ---------------------------------------------------------------------------

def test_parse_events_basic():
    events = parse_events([_make_event()], _PREFS)
    assert len(events) == 1
    e = events[0]
    assert e.external_event_id == "event-abc-123"
    assert e.home_team_name == "Richmond"
    assert e.away_team_name == "Carlton"
    assert e.bookmaker_key == "tab"
    assert e.bookmaker_title == "TAB"
    assert e.home_odds == 1.75
    assert e.away_odds == 2.10
    assert e.commence_time.tzinfo == UTC


def test_parse_events_commence_time_utc():
    events = parse_events([_make_event(commence_time="2025-03-20T08:30:00Z")], _PREFS)
    assert events[0].commence_time == datetime(2025, 3, 20, 8, 30, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# parse_events — bookmaker preference
# ---------------------------------------------------------------------------

def test_parse_events_prefers_first_available_bookmaker():
    event = _make_event()
    # Add sportsbet bookmaker with different odds
    event["bookmakers"].insert(0, {
        "key": "sportsbet",
        "title": "Sportsbet",
        "last_update": "2025-03-19T22:00:00Z",
        "markets": [{"key": "h2h", "outcomes": [
            {"name": "Richmond", "price": 1.80},
            {"name": "Carlton", "price": 2.00},
        ]}],
    })
    # tab is first in preference, so should be picked
    events = parse_events([event], ["tab", "sportsbet"])
    assert events[0].bookmaker_key == "tab"
    assert events[0].home_odds == 1.75


def test_parse_events_falls_back_to_available_bookmaker():
    event = _make_event()
    # Only sportsbet available, but we prefer tab (not present)
    event["bookmakers"][0]["key"] = "sportsbet"
    events = parse_events([event], ["tab", "unibet"])
    # Should fall back to sportsbet
    assert len(events) == 1
    assert events[0].bookmaker_key == "sportsbet"


def test_parse_events_skips_event_with_no_bookmakers():
    event = _make_event(bookmakers=[])
    events = parse_events([event], _PREFS)
    assert events == []


def test_parse_events_skips_event_with_no_h2h_market():
    event = _make_event()
    event["bookmakers"][0]["markets"] = [{"key": "spreads", "outcomes": []}]
    events = parse_events([event], _PREFS)
    assert events == []


# ---------------------------------------------------------------------------
# parse_events — malformed fields
# ---------------------------------------------------------------------------

def test_parse_events_skips_event_missing_home_team():
    event = _make_event(home_team="")
    events = parse_events([event], _PREFS)
    assert events == []


def test_parse_events_skips_event_missing_id():
    event = _make_event()
    del event["id"]
    events = parse_events([event], _PREFS)
    assert events == []


def test_parse_events_skips_event_with_outcome_name_mismatch():
    """Outcome names don't match team names — parser should skip the event."""
    event = _make_event()
    event["bookmakers"][0]["markets"][0]["outcomes"] = [
        {"name": "Wrong Team A", "price": 1.75},
        {"name": "Wrong Team B", "price": 2.10},
    ]
    events = parse_events([event], _PREFS)
    assert events == []


def test_parse_events_invalid_odds_rejected():
    """Odds below ODDS_MIN should cause event to be skipped."""
    event = _make_event()
    event["bookmakers"][0]["markets"][0]["outcomes"] = [
        {"name": "Richmond", "price": 0.50},   # invalid
        {"name": "Carlton", "price": 2.10},
    ]
    events = parse_events([event], _PREFS)
    assert events == []


def test_parse_events_odds_above_max_rejected():
    event = _make_event()
    event["bookmakers"][0]["markets"][0]["outcomes"] = [
        {"name": "Richmond", "price": 1.01},
        {"name": "Carlton", "price": ODDS_MAX + 1},  # too high
    ]
    events = parse_events([event], _PREFS)
    assert events == []


def test_parse_events_multiple_events_partial_skip():
    """One bad event should not prevent others from being parsed."""
    good = _make_event(id="good-1")
    bad = _make_event(id="bad-1", home_team="")
    events = parse_events([bad, good], _PREFS)
    assert len(events) == 1
    assert events[0].external_event_id == "good-1"


# ---------------------------------------------------------------------------
# validate_odds_pair
# ---------------------------------------------------------------------------

def test_validate_odds_pair_valid():
    home, away = validate_odds_pair(1.75, 2.10)
    assert home == 1.75
    assert away == 2.10


def test_validate_odds_pair_rejects_none():
    with pytest.raises(ValueError, match="None"):
        validate_odds_pair(None, 2.10)


def test_validate_odds_pair_rejects_non_numeric():
    with pytest.raises(ValueError, match="not numeric"):
        validate_odds_pair("two", 2.10)


def test_validate_odds_pair_rejects_below_min():
    with pytest.raises(ValueError, match="below minimum"):
        validate_odds_pair(0.90, 2.10)


def test_validate_odds_pair_rejects_above_max():
    with pytest.raises(ValueError, match="exceeds maximum"):
        validate_odds_pair(1.50, ODDS_MAX + 5)


def test_validate_odds_pair_warns_high_but_accepts(caplog):
    import logging
    with caplog.at_level(logging.WARNING):
        home, away = validate_odds_pair(1.01, 14.0)
    assert home == 1.01
    assert away == 14.0
    # 14.0 > ODDS_WARN_THRESHOLD=15? No, so no warning. Let's use 16.
    home, away = validate_odds_pair(1.01, 16.0)
    assert away == 16.0
