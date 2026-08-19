"""
collectors/parsers/odds_parser.py
----------------------------------
Parse and validate raw responses from The Odds API (the-odds-api.com).

These are pure functions with no I/O — safe to unit test without network calls.

The Odds API reference: https://the-odds-api.com/liveodds-api/
Sport key used: aussierules_afl
Markets used:   h2h (head-to-head, decimal odds)
Region:         au (Australian bookmakers)

Expected response shape per event:
  {
    "id": "...",
    "sport_key": "aussierules_afl",
    "commence_time": "2025-03-20T08:30:00Z",
    "home_team": "...",
    "away_team": "...",
    "bookmakers": [
      {
        "key": "tab",
        "title": "TAB",
        "last_update": "...",
        "markets": [
          {
            "key": "h2h",
            "outcomes": [
              {"name": "...", "price": 1.75},
              {"name": "...", "price": 2.10}
            ]
          }
        ]
      }
    ]
  }
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from loguru import logger

# Acceptable decimal odds range. Odds outside this range are rejected.
ODDS_MIN = 1.01
ODDS_MAX = 50.0
# Warn (but don't reject) if a single side exceeds this — unusual for 2-team H2H
ODDS_WARN_THRESHOLD = 15.0


@dataclass
class ParsedOddsEvent:
    """Normalised odds record ready for database upsert."""
    external_event_id: str      # The Odds API event id
    home_team_name: str         # raw name from API (needs normalization before DB lookup)
    away_team_name: str
    commence_time: datetime     # UTC-aware
    bookmaker_key: str          # e.g. 'tab', 'sportsbet'
    bookmaker_title: str        # e.g. 'TAB'
    home_odds: float
    away_odds: float
    odds_last_update: datetime  # when bookmaker last updated these odds
    parse_warnings: list[str] = field(default_factory=list)


class OddsParseError(ValueError):
    """Raised when the odds response cannot be parsed at all."""


def parse_events(
    raw: list,
    bookmaker_preference: list[str],
) -> list[ParsedOddsEvent]:
    """
    Parse the raw Odds API response into ParsedOddsEvent objects.

    Picks the first bookmaker from bookmaker_preference that has H2H odds
    for each event. Skips events with no usable bookmaker.

    Args:
        raw: List of event dicts from The Odds API.
        bookmaker_preference: Ordered list of bookmaker keys to try.

    Returns:
        One ParsedOddsEvent per successfully parsed event (one per event).
    """
    if not isinstance(raw, list):
        raise OddsParseError(
            f"Expected list from Odds API, got {type(raw).__name__}."
        )

    results: list[ParsedOddsEvent] = []
    for i, event in enumerate(raw):
        event_id = event.get("id", f"index-{i}")
        try:
            parsed = _parse_single_event(event, bookmaker_preference)
            if parsed:
                results.append(parsed)
        except Exception as exc:
            logger.warning(f"odds_parser: skipping event id={event_id}: {exc}")

    logger.debug(
        f"odds_parser: parsed {len(results)}/{len(raw)} events with usable odds."
    )
    return results


def validate_odds_pair(
    home_odds: float | None, away_odds: float | None
) -> tuple[float, float]:
    """
    Validate a decimal odds pair.

    Raises ValueError if either value is out of acceptable range.
    Logs a warning if values are suspiciously high.

    Returns:
        (home_odds, away_odds) as floats.
    """
    for label, val in (("home", home_odds), ("away", away_odds)):
        if val is None:
            raise ValueError(f"{label} odds is None.")
        try:
            val = float(val)
        except (TypeError, ValueError):
            raise ValueError(f"{label} odds {val!r} is not numeric.")
        if val < ODDS_MIN:
            raise ValueError(
                f"{label} odds {val} is below minimum {ODDS_MIN}. "
                "This likely indicates a data error."
            )
        if val > ODDS_MAX:
            raise ValueError(
                f"{label} odds {val} exceeds maximum {ODDS_MAX}. "
                "Rejecting as likely data error."
            )
        if val > ODDS_WARN_THRESHOLD:
            logger.warning(
                f"odds_parser: {label} odds {val} is unusually high "
                f"(>{ODDS_WARN_THRESHOLD}) — verify data source."
            )

    return float(home_odds), float(away_odds)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _parse_single_event(
    event: dict,
    bookmaker_preference: list[str],
) -> ParsedOddsEvent | None:
    """
    Parse one event dict. Returns None if no usable bookmaker found.

    Raises ValueError on malformed required fields.
    """
    warnings: list[str] = []

    event_id = str(event.get("id") or "")
    if not event_id:
        raise ValueError("Missing event id.")

    home_team = str(event.get("home_team") or "").strip()
    away_team = str(event.get("away_team") or "").strip()
    if not home_team or not away_team:
        raise ValueError(f"Missing team names in event {event_id}.")

    commence_time = _parse_iso_datetime(
        event.get("commence_time"), f"event {event_id}"
    )

    bookmakers: list[dict] = event.get("bookmakers") or []
    if not bookmakers:
        warnings.append(f"event {event_id}: no bookmakers in response.")
        logger.debug(f"odds_parser: event {event_id} has no bookmakers, skipping.")
        return None

    # Try preference list first, then fall back to any available bookmaker
    bm = _pick_bookmaker(bookmakers, bookmaker_preference, event_id)
    if bm is None:
        logger.debug(
            f"odds_parser: event {event_id} — no preferred bookmaker found "
            f"(available: {[b.get('key') for b in bookmakers]})."
        )
        return None

    h2h_market = _find_h2h_market(bm, event_id)
    if h2h_market is None:
        return None

    home_odds, away_odds = _extract_h2h_prices(
        h2h_market, home_team, away_team, event_id
    )
    # validate_odds_pair raises ValueError if invalid
    home_odds, away_odds = validate_odds_pair(home_odds, away_odds)

    odds_last_update = _parse_iso_datetime(
        bm.get("last_update"), f"bookmaker {bm.get('key')} in event {event_id}"
    )

    return ParsedOddsEvent(
        external_event_id=event_id,
        home_team_name=home_team,
        away_team_name=away_team,
        commence_time=commence_time,
        bookmaker_key=bm["key"],
        bookmaker_title=bm.get("title", bm["key"]),
        home_odds=round(home_odds, 4),
        away_odds=round(away_odds, 4),
        odds_last_update=odds_last_update,
        parse_warnings=warnings,
    )


def _pick_bookmaker(
    bookmakers: list[dict],
    preference: list[str],
    event_id: str,
) -> dict | None:
    """Return the first bookmaker in preference order that is present."""
    bm_by_key = {b["key"]: b for b in bookmakers if "key" in b}
    for key in preference:
        if key in bm_by_key:
            return bm_by_key[key]
    # Fall back: return first bookmaker available
    if bookmakers:
        fallback = bookmakers[0]
        logger.debug(
            f"odds_parser: event {event_id} — no preferred bookmaker, "
            f"using fallback {fallback.get('key')!r}."
        )
        return fallback
    return None


def _find_h2h_market(bm: dict, event_id: str) -> dict | None:
    """Return the h2h market dict from a bookmaker, or None."""
    markets: list[dict] = bm.get("markets") or []
    for market in markets:
        if market.get("key") == "h2h":
            return market
    logger.debug(
        f"odds_parser: event {event_id}, bookmaker {bm.get('key')!r}: "
        "no h2h market found."
    )
    return None


def _extract_h2h_prices(
    market: dict,
    home_team: str,
    away_team: str,
    event_id: str,
) -> tuple[float | None, float | None]:
    """
    Extract home and away prices from h2h market outcomes.

    Outcomes use team names — we match by exact string (normalization
    happens upstream in the ingest layer, not here).
    """
    outcomes: list[dict] = market.get("outcomes") or []
    prices: dict[str, float] = {
        o["name"]: float(o["price"])
        for o in outcomes
        if "name" in o and "price" in o
    }

    home_price = prices.get(home_team)
    away_price = prices.get(away_team)

    if home_price is None or away_price is None:
        available = list(prices.keys())
        raise ValueError(
            f"event {event_id}: could not find prices for "
            f"home={home_team!r} or away={away_team!r}. "
            f"Available outcome names: {available}."
        )

    return home_price, away_price


def _parse_iso_datetime(raw: str | None, context: str) -> datetime:
    """Parse ISO 8601 UTC datetime string. Raises ValueError if missing/invalid."""
    if not raw:
        raise ValueError(f"Missing datetime in {context}.")
    try:
        # Handle both 'Z' suffix and '+00:00'
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Cannot parse datetime {raw!r} in {context}: {exc}") from exc
