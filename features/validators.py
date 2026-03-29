"""
features/validators.py
-----------------------
Feature dataset integrity checks.

Three categories of checks:
  1. Leakage guards    — ensure no post-match information leaked into features.
  2. Null rate checks  — warn if a feature has too many missing values.
  3. Range checks      — flag values outside plausible AFL bounds.

All checks operate on a plain dict (one match's feature row) and return a
list of string issues (empty = clean). A non-empty list does not necessarily
mean the row must be dropped — callers decide.

These are defensive checks to catch bugs in the extractor layer, not
validators for user input.
"""

from __future__ import annotations

from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Leakage guards
# ---------------------------------------------------------------------------

# Columns that must never carry post-match information into feature rows
# for matches that have not yet been played.
_RESULT_COLUMNS: frozenset[str] = frozenset({
    "home_score",
    "away_score",
    "result",
})


def check_leakage(row: dict, match_time: datetime | None) -> list[str]:
    """
    Guard against result columns appearing in feature rows for future matches.

    Args:
        row:        Feature dict for one match.
        match_time: The match's scheduled time (UTC-aware). Pass None if unknown.

    Returns:
        List of issue strings (empty if clean).
    """
    issues: list[str] = []
    now = datetime.now(tz=timezone.utc)

    # For a future match, home_win should not be set
    if match_time is not None and match_time > now:
        if row.get("home_win") is not None:
            issues.append(
                f"Leakage: home_win={row['home_win']} is set for a future match "
                f"(match_time={match_time.isoformat()})."
            )

    # Result columns should never appear in a feature row
    for col in _RESULT_COLUMNS:
        if col in row:
            issues.append(
                f"Leakage: column {col!r} should not appear in feature rows."
            )

    return issues


# ---------------------------------------------------------------------------
# Null rate checks
# ---------------------------------------------------------------------------

# Warn when the null fraction for a column exceeds this threshold
_NULL_WARN_THRESHOLD: float = 0.30

# Columns that are expected to be sparse (no warning needed)
_EXPECTED_SPARSE: frozenset[str] = frozenset({
    "home_win",          # None for future/unplayed matches
    "bm_home_odds",      # only populated when odds data exists
    "bm_away_odds",
    "bm_home_implied_prob",
    "bm_away_implied_prob",
    "bm_overround",
    "home_rest_days",    # None for each team's first match
    "away_rest_days",
})


def check_null_rates(rows: list[dict]) -> list[str]:
    """
    Warn if a feature column has a high null rate across the dataset.

    Args:
        rows: List of feature dicts (one per match).

    Returns:
        List of warning strings (empty if clean).
    """
    if not rows:
        return []

    issues: list[str] = []
    n = len(rows)

    # Collect all unique columns
    all_cols: set[str] = set()
    for row in rows:
        all_cols.update(row.keys())

    for col in sorted(all_cols):
        if col in _EXPECTED_SPARSE:
            continue
        null_count = sum(1 for row in rows if row.get(col) is None)
        null_rate = null_count / n
        if null_rate > _NULL_WARN_THRESHOLD:
            issues.append(
                f"High null rate: {col!r} is None in {null_count}/{n} rows "
                f"({null_rate:.0%})."
            )

    return issues


# ---------------------------------------------------------------------------
# Range checks
# ---------------------------------------------------------------------------

_RANGE_CHECKS: list[tuple[str, float, float]] = [
    # (column, min_valid, max_valid)
    ("home_elo_pre",         800.0,  2200.0),
    ("away_elo_pre",         800.0,  2200.0),
    ("elo_diff",           -700.0,   700.0),
    ("home_win_rate_l10",    0.0,     1.0),
    ("away_win_rate_l10",    0.0,     1.0),
    ("home_avg_pts_for_l10", 0.0,   250.0),
    ("away_avg_pts_for_l10", 0.0,   250.0),
    ("home_avg_pts_against_l10", 0.0, 250.0),
    ("away_avg_pts_against_l10", 0.0, 250.0),
    ("bm_home_implied_prob", 0.0,     1.0),
    ("bm_away_implied_prob", 0.0,     1.0),
    ("bm_overround",         0.90,    1.40),
    ("bm_home_odds",         1.01,   50.0),
    ("bm_away_odds",         1.01,   50.0),
    ("home_rest_days",       0.0,   365.0),
    ("away_rest_days",       0.0,   365.0),
]


def check_ranges(row: dict) -> list[str]:
    """
    Check feature values fall within plausible AFL ranges.

    Args:
        row: Feature dict for one match.

    Returns:
        List of issue strings for out-of-range values (empty if clean).
    """
    issues: list[str] = []
    for col, lo, hi in _RANGE_CHECKS:
        val = row.get(col)
        if val is None:
            continue
        if not (lo <= val <= hi):
            issues.append(
                f"Range violation: {col}={val} is outside [{lo}, {hi}]."
            )
    return issues
