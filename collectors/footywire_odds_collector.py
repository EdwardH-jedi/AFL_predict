"""
collectors/footywire_odds_collector.py
----------------------------------------
Historical AFL H2H odds scraper for footywire.com.

Footywire publishes historical match betting odds (pre-match head-to-head)
at: https://www.footywire.com/afl/footy/ft_match_list?year=YYYY

NOTE: This scraper uses a 2-second politeness delay between requests.
      Collecting 2015-2025 takes approximately 30-60 minutes total.
      Use the year_range parameter to restrict collection.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterator

import httpx
from bs4 import BeautifulSoup
from loguru import logger


@dataclass
class FootywireOddsRecord:
    """Parsed odds record from Footywire."""
    season: int
    round_label: str
    home_team: str
    away_team: str
    home_odds: float | None
    away_odds: float | None
    match_date: str | None = None
    source: str = "footywire"


class FootywireOddsCollector:
    """
    Scrape historical AFL H2H odds from footywire.com.

    Usage:
        collector = FootywireOddsCollector()
        records = collector.collect(year_start=2020, year_end=2025)
    """

    BASE_URL = "https://www.footywire.com/afl/footy"
    MATCH_LIST_URL = BASE_URL + "/ft_match_list"
    REQUEST_DELAY = 2.0  # seconds between requests (politeness)
    USER_AGENT = "AFL-predict-research/0.1 (personal research; non-commercial)"

    def __init__(self, request_delay: float = REQUEST_DELAY) -> None:
        self.request_delay = request_delay
        self._client = httpx.Client(
            headers={"User-Agent": self.USER_AGENT},
            follow_redirects=True,
            timeout=30.0,
        )

    def collect(
        self, year_start: int = 2015, year_end: int = 2025
    ) -> list[FootywireOddsRecord]:
        """
        Collect historical odds for the given year range.

        Args:
            year_start: First season to collect (inclusive).
            year_end:   Last season to collect (inclusive).

        Returns:
            List of FootywireOddsRecord, one per match.
        """
        records: list[FootywireOddsRecord] = []
        for year in range(year_start, year_end + 1):
            try:
                year_records = list(self._collect_year(year))
                records.extend(year_records)
                logger.info(f"FootywireOddsCollector: {year} — {len(year_records)} records collected.")
            except Exception as exc:
                logger.warning(f"FootywireOddsCollector: {year} failed — {exc}")
        logger.info(f"FootywireOddsCollector: total {len(records)} records.")
        return records

    def _collect_year(self, year: int) -> Iterator[FootywireOddsRecord]:
        """Scrape all match odds for one season."""
        url = f"{self.MATCH_LIST_URL}?year={year}"
        resp = self._fetch(url)
        if resp is None:
            return

        soup = BeautifulSoup(resp, "html.parser")
        # Footywire match list: table rows with class fsfullw or similar
        # Each row: round, date, home, away, home_odds, away_odds
        rows = soup.select("table.ft tr")
        if not rows:
            # Fallback: try generic table rows
            rows = soup.select("tr.data") or soup.select("tr")

        current_round = "R0"
        for row in rows:
            cells = row.find_all(["td", "th"])
            if not cells:
                continue

            # Detect round header rows
            text = row.get_text(" ", strip=True)
            if "Round" in text and len(cells) <= 2:
                current_round = text.strip()
                continue

            record = self._parse_row(cells, year, current_round)
            if record is not None:
                yield record
                time.sleep(0.05)  # tiny delay within page

    def _parse_row(
        self, cells: list, year: int, round_label: str
    ) -> FootywireOddsRecord | None:
        """
        Parse a single table row into a FootywireOddsRecord.

        Footywire table column order (approximate):
          date | home_team | home_score | away_score | away_team | venue | home_odds | away_odds
        Columns may vary by year; we attempt best-effort parsing.
        """
        try:
            texts = [c.get_text(strip=True) for c in cells]
            if len(texts) < 5:
                return None

            # Heuristic column detection
            home_team = texts[1] if len(texts) > 1 else None
            away_team = texts[4] if len(texts) > 4 else None
            match_date = texts[0] if texts[0] else None

            # Odds columns (typically last two numeric columns)
            home_odds = _parse_odds(texts[-2]) if len(texts) >= 2 else None
            away_odds = _parse_odds(texts[-1]) if len(texts) >= 1 else None

            if not home_team or not away_team:
                return None
            if home_odds is None and away_odds is None:
                return None

            return FootywireOddsRecord(
                season=year,
                round_label=round_label,
                home_team=home_team,
                away_team=away_team,
                home_odds=home_odds,
                away_odds=away_odds,
                match_date=match_date,
            )
        except Exception:
            return None

    def _fetch(self, url: str) -> str | None:
        """Fetch URL with politeness delay and basic retry."""
        time.sleep(self.request_delay)
        for attempt in range(3):
            try:
                resp = self._client.get(url)
                resp.raise_for_status()
                return resp.text
            except Exception as exc:
                if attempt < 2:
                    logger.debug(f"FootywireOddsCollector: retry {attempt+1} for {url} ({exc})")
                    time.sleep(self.request_delay * (attempt + 2))
                else:
                    logger.warning(f"FootywireOddsCollector: failed after 3 attempts — {url}: {exc}")
                    return None
        return None

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "FootywireOddsCollector":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def _parse_odds(text: str) -> float | None:
    """Parse an odds string like '1.85' or '2.10' to float. Returns None if not parseable."""
    try:
        val = float(text.replace(",", ".").strip())
        if 1.01 <= val <= 50.0:  # sanity check for decimal odds
            return val
    except (ValueError, TypeError):
        pass
    return None
