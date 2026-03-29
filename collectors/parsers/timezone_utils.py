"""
collectors/parsers/timezone_utils.py
--------------------------------------
Centralised timezone helpers for all collector parsers.

Squiggle API returns game dates as "YYYY-MM-DD HH:MM:SS" in
Australian Eastern time (AEST UTC+10 / AEDT UTC+11). These must be
converted to UTC before storage.

NOTE: The AEST/AEDT assumption is based on Squiggle API documentation
and community usage. Verified against live data — dates match AFL schedule
published times in Melbourne local time.

All other timestamp sources (The Odds API) return ISO-8601 with explicit
UTC offset; those are parsed directly without going through this module.
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

# Australia/Melbourne handles both AEST (UTC+10) and AEDT (UTC+11)
# automatically based on the date.
MELBOURNE_TZ: ZoneInfo = ZoneInfo("Australia/Melbourne")

# Format used by Squiggle for the 'date' field: "2025-04-12 14:10:00"
SQUIGGLE_DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"


def squiggle_local_to_utc(raw_date: str) -> datetime:
    """
    Parse a Squiggle date string (AEST/AEDT local) and return UTC-aware datetime.

    Args:
        raw_date: Date string in "YYYY-MM-DD HH:MM:SS" format (Melbourne local time).

    Returns:
        UTC-aware datetime.

    Raises:
        ValueError: If the string cannot be parsed.
    """
    # Only use the first 19 characters to safely ignore any trailing chars
    naive = datetime.strptime(raw_date[:19], SQUIGGLE_DATE_FORMAT)
    local = naive.replace(tzinfo=MELBOURNE_TZ)
    return local.astimezone(timezone.utc)


def parse_iso_utc(raw: str) -> datetime:
    """
    Parse an ISO-8601 timestamp that already carries a UTC offset.

    Handles both 'Z' suffix and '+00:00' format.

    Args:
        raw: ISO-8601 datetime string (e.g. "2025-04-12T04:10:00Z").

    Returns:
        UTC-aware datetime.

    Raises:
        ValueError: If the string cannot be parsed.
    """
    raw = raw.strip()
    # Replace trailing Z with +00:00 for fromisoformat compatibility
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    dt = datetime.fromisoformat(raw)
    return dt.astimezone(timezone.utc)
