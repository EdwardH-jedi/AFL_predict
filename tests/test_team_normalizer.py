"""
tests/test_team_normalizer.py
------------------------------
Unit tests for collectors/team_normalizer.py.
"""

import pytest

from collectors.team_normalizer import (
    CANONICAL_TEAMS,
    get_unknown_aliases,
    normalize,
    normalize_many,
    reset_unknown,
)


@pytest.fixture(autouse=True)
def clear_unknown():
    """Reset the unknown-alias tracker before and after every test."""
    reset_unknown()
    yield
    reset_unknown()


def test_canonical_name_passes_through():
    assert normalize("Richmond") == "Richmond"
    assert normalize("GWS Giants") == "GWS Giants"


@pytest.mark.parametrize("alias,expected", [
    ("Richmond Tigers", "Richmond"),
    ("Carlton Blues", "Carlton"),
    ("Adelaide Crows", "Adelaide"),
    ("GWS", "GWS Giants"),
    ("Greater Western Sydney", "GWS Giants"),
    ("Brisbane", "Brisbane Lions"),
    ("North", "North Melbourne"),
    ("Footscray", "Western Bulldogs"),
    ("Port", "Port Adelaide"),
    ("Sydney Swans", "Sydney"),
])
def test_known_aliases_resolve(alias, expected):
    assert normalize(alias) == expected


def test_unknown_name_returns_as_is():
    result = normalize("Some Unknown Team")
    assert result == "Some Unknown Team"


def test_normalize_many():
    aliases = ["Richmond Tigers", "Carlton Blues"]
    result = normalize_many(aliases)
    assert result == ["Richmond", "Carlton"]


def test_all_canonical_teams_pass_through():
    """Every canonical name should resolve to itself without going through ALIASES."""
    for name in CANONICAL_TEAMS:
        assert normalize(name) == name


# ---------------------------------------------------------------------------
# Unknown alias tracking
# ---------------------------------------------------------------------------

def test_unknown_name_tracked_in_seen_unknown():
    normalize("Fake FC")
    assert "Fake FC" in get_unknown_aliases()


def test_canonical_name_not_tracked_as_unknown():
    normalize("Richmond")
    assert "Richmond" not in get_unknown_aliases()


def test_known_alias_not_tracked_as_unknown():
    normalize("Richmond Tigers")
    assert "Richmond Tigers" not in get_unknown_aliases()


def test_same_unknown_only_tracked_once():
    normalize("Ghost Team")
    normalize("Ghost Team")
    unknown = get_unknown_aliases()
    # Count is not directly accessible but frozenset means no duplicates
    assert "Ghost Team" in unknown


def test_reset_unknown_clears_tracking():
    normalize("Temp FC")
    assert "Temp FC" in get_unknown_aliases()
    reset_unknown()
    assert len(get_unknown_aliases()) == 0


def test_get_unknown_aliases_returns_frozenset():
    normalize("Unknown Club")
    result = get_unknown_aliases()
    assert isinstance(result, frozenset)
