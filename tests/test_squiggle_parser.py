"""
tests/test_squiggle_parser.py
------------------------------
Unit tests for collectors/parsers/squiggle_parser.py.

No network calls, no database — pure function testing.
"""

from datetime import UTC

import pytest

from collectors.parsers.squiggle_parser import (
    SquiggleParseError,
    _derive_result,
    parse_games,
    parse_teams,
)

# ---------------------------------------------------------------------------
# Fixtures (reusable test data)
# ---------------------------------------------------------------------------

def _make_game(**overrides) -> dict:
    """Return a minimal valid Squiggle game dict."""
    base = {
        "id": 1001,
        "year": 2025,
        "round": 1,
        "roundname": "Round 1",
        "hteam": "Richmond",
        "ateam": "Carlton",
        "hteamid": 14,
        "ateamid": 3,
        "date": "2025-03-20 19:30:00",
        "venue": "MCG",
        "hscore": None,
        "ascore": None,
        "winner": None,
        "complete": 0,
        "is_final": 0,
    }
    base.update(overrides)
    return base


def _make_team(**overrides) -> dict:
    base = {"id": 14, "name": "Richmond", "abbrev": "RICH", "state": "VIC"}
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# parse_games — structural errors
# ---------------------------------------------------------------------------

def test_parse_games_raises_on_non_dict():
    with pytest.raises(SquiggleParseError, match="Unexpected"):
        parse_games([])


def test_parse_games_raises_on_missing_games_key():
    with pytest.raises(SquiggleParseError, match="Unexpected"):
        parse_games({"other": []})


def test_parse_games_returns_empty_for_empty_list():
    result = parse_games({"games": []})
    assert result == []


# ---------------------------------------------------------------------------
# parse_games — valid game
# ---------------------------------------------------------------------------

def test_parse_games_basic_fixture():
    raw = {"games": [_make_game()]}
    games = parse_games(raw)
    assert len(games) == 1
    g = games[0]
    assert g.external_id == "1001"
    assert g.season == 2025
    assert g.round_number == 1
    assert g.round_label == "Round 1"
    assert g.home_team_name == "Richmond"
    assert g.away_team_name == "Carlton"
    assert g.home_team_external_id == "14"
    assert g.away_team_external_id == "3"
    assert g.venue == "MCG"
    assert g.is_complete is False
    assert g.result is None
    assert g.home_score is None
    assert g.away_score is None


def test_parse_games_complete_home_win():
    raw = {"games": [_make_game(
        complete=100, winner="Richmond", hscore=102, ascore=89
    )]}
    games = parse_games(raw)
    g = games[0]
    assert g.is_complete is True
    assert g.result == "home"
    assert g.home_score == 102
    assert g.away_score == 89


def test_parse_games_complete_away_win():
    raw = {"games": [_make_game(
        complete=100, winner="Carlton", hscore=75, ascore=110
    )]}
    games = parse_games(raw)
    assert games[0].result == "away"


def test_parse_games_draw_empty_winner():
    raw = {"games": [_make_game(
        complete=100, winner="", hscore=80, ascore=80
    )]}
    games = parse_games(raw)
    assert games[0].result == "draw"


def test_parse_games_complete_but_no_scores_produces_warning():
    raw = {"games": [_make_game(complete=100, winner="Richmond", hscore=None, ascore=None)]}
    games = parse_games(raw)
    assert len(games) == 1  # still parsed
    assert any("scores missing" in w for w in games[0].parse_warnings)


def test_parse_games_skips_game_with_missing_hteamid():
    """A game missing required hteamid should be skipped, not crash the parser."""
    bad_game = _make_game()
    del bad_game["hteamid"]
    raw = {"games": [bad_game, _make_game(id=1002)]}
    games = parse_games(raw)
    # Only the valid second game should be returned
    assert len(games) == 1
    assert games[0].external_id == "1002"


def test_parse_games_skips_game_with_empty_hteam():
    bad_game = _make_game(hteam="")
    raw = {"games": [bad_game]}
    games = parse_games(raw)
    assert games == []


# ---------------------------------------------------------------------------
# parse_games — match time
# ---------------------------------------------------------------------------

def test_parse_games_match_time_is_utc():
    raw = {"games": [_make_game(date="2025-03-20 19:30:00")]}
    games = parse_games(raw)
    mt = games[0].match_time
    assert mt is not None
    assert mt.tzinfo == UTC
    # 19:30 AEDT (UTC+11) = 08:30 UTC
    assert mt.hour == 8
    assert mt.minute == 30


def test_parse_games_match_time_none_on_missing_date():
    raw = {"games": [_make_game(date=None)]}
    games = parse_games(raw)
    assert games[0].match_time is None
    assert any("no date" in w for w in games[0].parse_warnings)


def test_parse_games_match_time_none_on_bad_date():
    raw = {"games": [_make_game(date="not-a-date")]}
    games = parse_games(raw)
    assert games[0].match_time is None
    assert any("could not parse date" in w for w in games[0].parse_warnings)


# ---------------------------------------------------------------------------
# parse_games — is_final flag
# ---------------------------------------------------------------------------

def test_parse_games_is_final_flag():
    raw = {"games": [_make_game(is_final=1)]}
    games = parse_games(raw)
    assert games[0].is_final is True


# ---------------------------------------------------------------------------
# parse_teams
# ---------------------------------------------------------------------------

def test_parse_teams_raises_on_bad_structure():
    with pytest.raises(SquiggleParseError):
        parse_teams({"wrong_key": []})


def test_parse_teams_basic():
    raw = {"teams": [_make_team()]}
    teams = parse_teams(raw)
    assert len(teams) == 1
    t = teams[0]
    assert t.external_id == "14"
    assert t.name == "Richmond"
    assert t.short_name == "RICH"
    assert t.state == "VIC"


def test_parse_teams_missing_abbrev_uses_name_prefix():
    raw = {"teams": [_make_team(abbrev=None)]}
    teams = parse_teams(raw)
    assert len(teams[0].short_name) <= 10  # fallback used


def test_parse_teams_skips_team_with_missing_id():
    bad = {"name": "Unknown", "abbrev": "UNK"}  # no 'id'
    raw = {"teams": [bad, _make_team()]}
    teams = parse_teams(raw)
    assert len(teams) == 1
    assert teams[0].name == "Richmond"


# ---------------------------------------------------------------------------
# _derive_result (internal helper — tested directly for clarity)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("winner,expected", [
    ("Richmond", "home"),
    ("Carlton", "away"),
    ("", "draw"),
    (None, "draw"),
])
def test_derive_result(winner, expected):
    warnings: list = []
    result = _derive_result(winner, "Richmond", "Carlton", 1, warnings)
    assert result == expected


def test_derive_result_unknown_winner_treated_as_draw():
    warnings: list = []
    result = _derive_result("SomeOtherTeam", "Richmond", "Carlton", 1, warnings)
    assert result == "draw"
    assert any("matches neither" in w for w in warnings)
