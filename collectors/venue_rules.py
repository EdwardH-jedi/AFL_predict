"""
collectors/venue_rules.py
--------------------------
Home-ground and neutral-venue rules for AFL fixtures.

Used at ingestion time (afl_transformer) to set is_neutral_venue on Match rows.

A match is neutral when the API-designated home team is NOT playing at one
of their registered home grounds.

Sources:
  - AFL official ground assignments (2024/2025 season)
  - Gather Round venues (all neutral by definition)
  - Interstate carnival / one-off venues that belong to no AFL team
"""

from __future__ import annotations

# Maps canonical team name → set of venue strings used by Squiggle API
# that are that team's registered home grounds.
TEAM_HOME_VENUES: dict[str, frozenset[str]] = {
    "Adelaide":          frozenset({"Adelaide Oval"}),
    "Brisbane Lions":    frozenset({"Gabba"}),
    "Carlton":           frozenset({"Docklands", "M.C.G."}),
    "Collingwood":       frozenset({"M.C.G."}),
    "Essendon":          frozenset({"Docklands"}),
    "Fremantle":         frozenset({"Perth Stadium"}),
    "Geelong":           frozenset({"Kardinia Park"}),
    "Gold Coast":        frozenset({"Carrara"}),
    "GWS Giants":        frozenset({"Sydney Showground"}),
    "Hawthorn":          frozenset({"M.C.G."}),
    "Melbourne":         frozenset({"M.C.G."}),
    "North Melbourne":   frozenset({"Docklands"}),
    "Port Adelaide":     frozenset({"Adelaide Oval"}),
    "Richmond":          frozenset({"M.C.G."}),
    "St Kilda":          frozenset({"Docklands"}),
    "Sydney":            frozenset({"S.C.G."}),
    "West Coast":        frozenset({"Perth Stadium"}),
    "Western Bulldogs":  frozenset({"Docklands"}),
}

# Venues that are always neutral (used for Gather Round, carnivals, etc.)
# No AFL team lists these as a home ground.
ALWAYS_NEUTRAL_VENUES: frozenset[str] = frozenset({
    "Barossa Park",
    "Norwood Oval",
    "York Park",
    "Traeger Park",
    "Hands Oval",
    "Marrara Oval",
    "Manuka Oval",
    "Bellerive Oval",
    "Sydney Showground Stadium",  # alternate Squiggle name
})


# State that each team calls home. Used by TravelExtractor.
TEAM_HOME_STATE: dict[str, str] = {
    "Adelaide":         "SA",
    "Brisbane Lions":   "QLD",
    "Carlton":          "VIC",
    "Collingwood":      "VIC",
    "Essendon":         "VIC",
    "Fremantle":        "WA",
    "Geelong":          "VIC",
    "Gold Coast":       "QLD",
    "GWS Giants":       "NSW",
    "Hawthorn":         "VIC",
    "Melbourne":        "VIC",
    "North Melbourne":  "VIC",
    "Port Adelaide":    "SA",
    "Richmond":         "VIC",
    "St Kilda":         "VIC",
    "Sydney":           "NSW",
    "West Coast":       "WA",
    "Western Bulldogs": "VIC",
}

# State each AFL venue is located in.
VENUE_STATE: dict[str, str] = {
    "M.C.G.":                   "VIC",
    "Docklands":                 "VIC",
    "Kardinia Park":             "VIC",
    "Adelaide Oval":             "SA",
    "Norwood Oval":              "SA",
    "Perth Stadium":             "WA",
    "Gabba":                     "QLD",
    "Carrara":                   "QLD",
    "S.C.G.":                    "NSW",
    "Sydney Showground":         "NSW",
    "Sydney Showground Stadium": "NSW",
    "York Park":                 "TAS",
    "Bellerive Oval":            "TAS",
    "Marrara Oval":              "NT",
    "Traeger Park":              "NT",
    "Manuka Oval":               "ACT",
    # Gather Round / interstate carnivals
    "Barossa Park":              "SA",
    "Riverway Stadium":          "QLD",
    "Cazalys Stadium":           "QLD",
    "Hands Oval":                "WA",
    "TIO Stadium":               "NT",
}

# Approximate straight-line distance (km) between state capitals.
# Used to add a continuous travel burden feature.
STATE_PAIR_DISTANCE_KM: dict[frozenset, float] = {
    frozenset({"VIC", "SA"}):  730.0,
    frozenset({"VIC", "NSW"}): 870.0,
    frozenset({"VIC", "QLD"}): 1730.0,
    frozenset({"VIC", "WA"}):  2720.0,
    frozenset({"VIC", "TAS"}): 310.0,
    frozenset({"VIC", "NT"}):  3140.0,
    frozenset({"VIC", "ACT"}): 650.0,
    frozenset({"SA", "NSW"}):  1170.0,
    frozenset({"SA", "QLD"}):  1600.0,
    frozenset({"SA", "WA"}):   2130.0,
    frozenset({"SA", "TAS"}):  1020.0,
    frozenset({"SA", "NT"}):   2420.0,
    frozenset({"SA", "ACT"}):  990.0,
    frozenset({"NSW", "QLD"}): 980.0,
    frozenset({"NSW", "WA"}):  3940.0,
    frozenset({"NSW", "TAS"}): 1100.0,
    frozenset({"NSW", "NT"}):  3140.0,
    frozenset({"NSW", "ACT"}): 280.0,
    frozenset({"QLD", "WA"}):  4390.0,
    frozenset({"QLD", "TAS"}): 2100.0,
    frozenset({"QLD", "NT"}):  2800.0,
    frozenset({"QLD", "ACT"}): 1250.0,
    frozenset({"WA", "TAS"}):  3560.0,
    frozenset({"WA", "NT"}):   2650.0,
    frozenset({"WA", "ACT"}):  3750.0,
    frozenset({"NT", "TAS"}):  4100.0,
    frozenset({"NT", "ACT"}):  3160.0,
    frozenset({"TAS", "ACT"}): 960.0,
}


def is_neutral_venue(home_team_name: str, venue: str | None) -> bool:
    """
    Return True if the home team is NOT playing at their home ground.

    Args:
        home_team_name: Canonical team name (Squiggle authority).
        venue:          Raw venue string from Squiggle (may be None).

    Returns:
        True  → neutral venue (zero ELO home advantage).
        False → home ground or unknown (apply normal home advantage).
    """
    if venue is None:
        return False  # No venue info — assume home ground (conservative)

    if venue in ALWAYS_NEUTRAL_VENUES:
        return True

    home_grounds = TEAM_HOME_VENUES.get(home_team_name)
    if home_grounds is None:
        return False  # Unknown team — conservative default

    return venue not in home_grounds
