"""
collectors/team_normalizer.py
------------------------------
Canonical AFL team names and alias resolution.

Squiggle API is the authority for canonical names. All other sources
(The Odds API, scrapers, manual entry) must be mapped through this module
before touching the database.

If a name is not found in ALIASES it is returned as-is (with a warning).
Unknown names are tracked in _SEEN_UNKNOWN for reporting at end of each
ingestion run via get_unknown_aliases() / reset_unknown().
"""

from loguru import logger

# Module-level set of alias strings not found in ALIASES or CANONICAL_TEAMS.
# Populated by normalize(); cleared between runs by reset_unknown().
_SEEN_UNKNOWN: set[str] = set()

# Canonical names exactly as returned by the Squiggle API
CANONICAL_TEAMS: frozenset[str] = frozenset({
    "Adelaide",
    "Brisbane Lions",
    "Carlton",
    "Collingwood",
    "Essendon",
    "Fremantle",
    "Geelong",
    "Gold Coast",
    "GWS Giants",
    "Hawthorn",
    "Melbourne",
    "North Melbourne",
    "Port Adelaide",
    "Richmond",
    "St Kilda",
    "Sydney",
    "West Coast",
    "Western Bulldogs",
})

# Alias → canonical name.
# Sources: The Odds API full names, common abbreviations, historical variants.
ALIASES: dict[str, str] = {
    # Adelaide
    "Adelaide Crows": "Adelaide",
    "Adelaide FC": "Adelaide",
    # Brisbane
    "Brisbane": "Brisbane Lions",
    "Brisbane Bear": "Brisbane Lions",
    # Carlton
    "Carlton Blues": "Carlton",
    # Collingwood
    "Collingwood Magpies": "Collingwood",
    # Essendon
    "Essendon Bombers": "Essendon",
    # Fremantle
    "Fremantle Dockers": "Fremantle",
    # Geelong
    "Geelong Cats": "Geelong",
    # Gold Coast
    "Gold Coast Suns": "Gold Coast",
    # GWS
    "GWS": "GWS Giants",
    "Greater Western Sydney": "GWS Giants",
    "Greater Western Sydney Giants": "GWS Giants",
    "Giants": "GWS Giants",
    # Hawthorn
    "Hawthorn Hawks": "Hawthorn",
    # Melbourne
    "Melbourne Demons": "Melbourne",
    "Demons": "Melbourne",
    # North Melbourne
    "North Melbourne Kangaroos": "North Melbourne",
    "Kangaroos": "North Melbourne",
    "North": "North Melbourne",
    # Port Adelaide
    "Port Adelaide Power": "Port Adelaide",
    "Port": "Port Adelaide",
    # Richmond
    "Richmond Tigers": "Richmond",
    # St Kilda
    "St Kilda Saints": "St Kilda",
    "Saint Kilda": "St Kilda",
    # Sydney
    "Sydney Swans": "Sydney",
    "Swans": "Sydney",
    # West Coast
    "West Coast Eagles": "West Coast",
    "Eagles": "West Coast",
    # Western Bulldogs
    "Bulldogs": "Western Bulldogs",
    "Western Bulldogs FC": "Western Bulldogs",
    "Footscray": "Western Bulldogs",
}


def normalize(name: str) -> str:
    """
    Return the canonical Squiggle team name for any known alias.

    If the name is already canonical, returns it unchanged.
    If the name is an alias, resolves to canonical.
    If unknown, logs a warning, records in _SEEN_UNKNOWN, and returns
    the input unchanged.
    """
    if name in CANONICAL_TEAMS:
        return name
    canonical = ALIASES.get(name)
    if canonical:
        return canonical
    if name not in _SEEN_UNKNOWN:
        _SEEN_UNKNOWN.add(name)
        logger.warning(
            f"team_normalizer: unknown team name {name!r} — "
            "add it to ALIASES if it is a valid AFL team."
        )
    return name


def normalize_many(names: list[str]) -> list[str]:
    """Normalize a list of team names."""
    return [normalize(n) for n in names]


def get_unknown_aliases() -> frozenset[str]:
    """Return all unrecognised team names seen since the last reset_unknown() call."""
    return frozenset(_SEEN_UNKNOWN)


def reset_unknown() -> None:
    """Clear the set of seen unknown aliases (call at the start of each ingestion run)."""
    _SEEN_UNKNOWN.clear()
