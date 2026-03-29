"""
collectors/odds_api_collector.py
---------------------------------
HTTP client for The Odds API (the-odds-api.com).

Provides AFL H2H pre-match odds from AU-region bookmakers (TAB, Sportsbet, etc.).

Free tier: 500 requests/month. Each call costs 1 request per event returned.
Get a free key at: https://the-odds-api.com

INTEGRATION POINT: This is the selected odds data source.
  - Sport key: aussierules_afl
  - Region:    au (Australian bookmakers)
  - Market:    h2h (head-to-head, decimal odds)
  - TODO: Confirm TAB odds are present in your subscription tier.
    TAB availability varies; sportsbet/unibet are more reliably present.

This module handles:
  - HTTP requests with retry
  - Quota tracking via response headers (x-requests-remaining)
  - Raw response persistence to disk before parsing
  - No database access
"""

from typing import Any

import httpx
from loguru import logger
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from collectors.snapshot_store import SnapshotStore
from config.settings import get_settings

settings = get_settings()

_SPORT_KEY = "aussierules_afl"
_MARKET = "h2h"
_ODDS_FORMAT = "decimal"


class OddsApiCollector:
    """
    Fetches raw AFL H2H odds from The Odds API.

    Requires ODDS_API_KEY in settings. Returns empty list if key is missing.
    All methods save raw responses to disk before returning.
    """

    def __init__(self) -> None:
        self.base_url = settings.odds_api_base_url.rstrip("/")
        self.api_key = settings.odds_api_key
        self.region = settings.odds_api_region
        self._snapshots = SnapshotStore(settings.raw_snapshots_dir, source="odds_api")
        self._last_requests_remaining: int | None = None

    def fetch_h2h_odds(self) -> list[dict]:
        """
        Fetch current H2H odds for all upcoming AFL matches.

        Returns:
            List of event dicts (raw from The Odds API).
            Returns empty list if ODDS_API_KEY is not configured.
        """
        if not self.api_key:
            logger.warning(
                "odds_api_collector: ODDS_API_KEY not set — skipping odds fetch. "
                "Set it in .env to enable odds ingestion."
            )
            return []

        endpoint = f"/v4/sports/{_SPORT_KEY}/odds/"
        params = {
            "apiKey": self.api_key,
            "regions": self.region,
            "markets": _MARKET,
            "oddsFormat": _ODDS_FORMAT,
        }

        logger.info(
            f"odds_api_collector: fetching {_SPORT_KEY} {_MARKET} odds "
            f"(region={self.region})"
        )
        raw, remaining = self._get(endpoint, params)
        self._last_requests_remaining = remaining

        if remaining is not None:
            logger.info(f"odds_api_collector: {remaining} API requests remaining this month.")
            if remaining < 50:
                logger.warning(
                    f"odds_api_collector: only {remaining} requests remaining — "
                    "consider reducing fetch frequency."
                )

        self._snapshots.save(raw, "h2h_odds")
        return raw if isinstance(raw, list) else []

    @property
    def requests_remaining(self) -> int | None:
        """Last known request quota remaining, or None if not yet fetched."""
        return self._last_requests_remaining

    @property
    def snapshots(self) -> SnapshotStore:
        """Expose snapshot store for replay/testing."""
        return self._snapshots

    # ---------------------------------------------------------------------------
    # Private
    # ---------------------------------------------------------------------------

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(httpx.HTTPError),
        reraise=True,
    )
    def _get(self, endpoint: str, params: dict) -> tuple[Any, int | None]:
        """
        Execute authenticated GET. Returns (response_json, requests_remaining).

        INTEGRATION POINT: The Odds API authentication is via ?apiKey= query param.
        Rate limit info is in response header 'x-requests-remaining'.
        Raises httpx.HTTPStatusError on 4xx/5xx (triggers tenacity retry for 5xx).
        On 401: bad API key — do not retry.
        """
        url = f"{self.base_url}{endpoint}"
        response = httpx.get(url, params=params, timeout=30, follow_redirects=True)

        # 401 = bad key, don't retry
        if response.status_code == 401:
            logger.error(
                "odds_api_collector: 401 Unauthorized — check ODDS_API_KEY in .env."
            )
            response.raise_for_status()

        response.raise_for_status()

        remaining_header = response.headers.get("x-requests-remaining")
        remaining = int(remaining_header) if remaining_header else None

        return response.json(), remaining

