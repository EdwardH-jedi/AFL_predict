"""
collectors/squiggle_collector.py
---------------------------------
HTTP client for the Squiggle AFL data API (squiggle.com.au).

Squiggle is a free, public API maintained by a community volunteer.
Usage policy: set a descriptive User-Agent, don't hammer with requests.
Docs: https://api.squiggle.com.au/

This module handles:
  - HTTP requests with retry + respectful rate limiting
  - Raw response persistence to disk before any parsing
  - No database access (pure I/O layer)
"""

import time
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

# Squiggle requests must include a User-Agent per their usage policy
_USER_AGENT = settings.squiggle_user_agent

# Polite delay between requests to avoid hammering the volunteer-run service
_REQUEST_DELAY_SECONDS = 1.0


class SquiggleCollector:
    """
    Fetches raw AFL data from the Squiggle API and saves snapshots to disk.

    All methods return the raw parsed JSON dict/list — parsing/validation
    is handled by collectors/parsers/squiggle_parser.py.
    """

    # INTEGRATION POINT: Squiggle API
    # Base URL and query format: GET https://api.squiggle.com.au/?q=<query>;<params>
    # This is a stable, community-maintained resource — not an official AFL endpoint.

    def __init__(self) -> None:
        self.base_url = settings.squiggle_base_url.rstrip("/")
        self._snapshots = SnapshotStore(settings.raw_snapshots_dir, source="squiggle")

    def fetch_games(self, season: int, round_number: int | None = None) -> dict:
        """
        Fetch all games for a season (and optionally a specific round).

        Saves raw response to disk before returning.

        Args:
            season:       AFL season year (e.g. 2025)
            round_number: Optional round filter (1-based). None fetches all rounds.

        Returns:
            Raw API response dict with 'games' key.
        """
        params: dict[str, Any] = {"q": "games", "year": season}
        if round_number is not None:
            params["round"] = round_number

        label = f"games_{season}" + (f"_r{round_number}" if round_number else "")
        logger.info(f"squiggle_collector: fetching games season={season} round={round_number}")

        raw = self._get(params)
        self._snapshots.save(raw, label)
        return raw

    def fetch_teams(self) -> dict:
        """
        Fetch all AFL team reference data.

        Returns:
            Raw API response dict with 'teams' key.
        """
        logger.info("squiggle_collector: fetching teams")
        raw = self._get({"q": "teams"})
        self._snapshots.save(raw, "teams")
        return raw

    # ---------------------------------------------------------------------------
    # Private
    # ---------------------------------------------------------------------------

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(httpx.HTTPError),
        reraise=True,
    )
    def _get(self, params: dict) -> Any:
        """
        Execute a GET request to the Squiggle API with retry on HTTP errors.

        INTEGRATION POINT: Squiggle query format is ?q=<type>;<param>=<val>
        The httpx params dict encodes naturally as ?q=games&year=2025 which
        Squiggle also accepts. No auth header required.
        """
        headers = {
            "User-Agent": _USER_AGENT,
            "Accept": "application/json",
        }
        # Polite delay to avoid rate-limiting the volunteer service
        time.sleep(_REQUEST_DELAY_SECONDS)

        response = httpx.get(
            self.base_url,
            params=params,
            headers=headers,
            timeout=30,
            follow_redirects=True,
        )
        response.raise_for_status()
        return response.json()

    @property
    def snapshots(self) -> SnapshotStore:
        """Expose snapshot store for direct access (e.g. replay in tests)."""
        return self._snapshots
