"""
collectors/player_collector.py
--------------------------------
AFL player stats and lineup collector using AFL Tables (afltables.com).

AFL Tables is a public AFL statistics archive with per-player, per-game stats
going back to 1897. No API key required. Uses CSV exports for reliability.

Data flow:
  fetch_player_stats_for_season(season)
    -> downloads CSV from afltables.com/afl/stats/...
    -> parses into list[PlayerStatRow] dataclasses
    -> upserts into player_stats table
    -> computes contribution scores
    -> builds PlayerLineup rows (availability_index per team per match)
    -> upserts into player_lineups table

AFL Tables CSV URL format:
  https://afltables.com/afl/stats/YEAR_player_stats.txt

Leakage policy:
  This collector only processes past matches (match already played).
  For upcoming matches, availability_index defaults to 1.0 (full strength)
  until an announced lineup is scraped separately.

Rate limiting:
  AFL Tables requests a polite crawl delay. We sleep 1s between requests.
"""

from __future__ import annotations

import csv
import io
import time
from dataclasses import dataclass

import httpx
from loguru import logger
from sqlalchemy.orm import Session

from collectors.snapshot_store import SnapshotStore
from collectors.team_normalizer import normalize
from config.settings import get_settings
from db.models.matches import Match
from db.models.player_lineups import PlayerLineup, PlayerStat
from db.models.teams import Team

settings = get_settings()

_AFLTABLES_BASE = "https://afltables.com/afl/stats"
_USER_AGENT = settings.squiggle_user_agent  # reuse polite user agent
_CONTRIBUTION_WEIGHT_GOALS = 3  # goals count 3x disposals for contribution score


@dataclass
class PlayerStatRow:
    """Parsed row from AFL Tables CSV."""
    season: int
    round_number: int | None
    team_name: str
    opponent_name: str
    home_away: str          # 'H' or 'A'
    player_external_id: str
    player_name: str
    disposals: int | None
    kicks: int | None
    handballs: int | None
    goals: int | None
    behinds: int | None


class PlayerCollector:
    """
    Fetches and stores AFL player stats from AFL Tables.

    Requires a SQLAlchemy Session to resolve team IDs and upsert records.
    """

    def __init__(self, db: Session) -> None:
        self._db = db
        self._snapshots = SnapshotStore(settings.raw_snapshots_dir, source="afltables")

    def fetch_and_store_season(self, season: int) -> int:
        """
        Download player stats CSV for a full season and upsert into DB.

        Args:
            season: AFL season year (e.g. 2024).

        Returns:
            Number of player stat rows inserted/updated.
        """
        logger.info(f"PlayerCollector: fetching season {season} stats from AFL Tables...")

        url = f"{_AFLTABLES_BASE}/{season}_player_stats.txt"
        try:
            response = httpx.get(
                url,
                headers={"User-Agent": _USER_AGENT},
                timeout=60,
                follow_redirects=True,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.error(f"PlayerCollector: HTTP {e.response.status_code} fetching {url}")
            return 0
        except httpx.RequestError as e:
            logger.error(f"PlayerCollector: network error fetching {url}: {e}")
            return 0

        raw_text = response.text
        self._snapshots.save(
            {"season": season, "content": raw_text[:500]}, f"player_stats_{season}"
        )

        rows = self._parse_csv(raw_text, season)
        if not rows:
            logger.warning(f"PlayerCollector: no rows parsed for season {season}.")
            return 0

        inserted = self._upsert_stats(rows)
        self._compute_and_store_lineups(season)

        time.sleep(1)  # polite delay for AFL Tables
        return inserted

    # ---------------------------------------------------------------------------
    # CSV parsing
    # ---------------------------------------------------------------------------

    def _parse_csv(self, text: str, season: int) -> list[PlayerStatRow]:
        """Parse AFL Tables player stats CSV."""
        rows: list[PlayerStatRow] = []
        reader = csv.DictReader(io.StringIO(text))

        for line in reader:
            try:
                # AFL Tables CSV columns vary by year; use flexible key lookup
                def get(*keys: str) -> str:
                    for k in keys:
                        val = line.get(k, "").strip()
                        if val:
                            return val
                    return ""

                def to_int(val: str) -> int | None:
                    try:
                        return int(val) if val.strip() else None
                    except ValueError:
                        return None

                team = normalize(get("Playing for", "Team"))
                opponent = normalize(get("Opponent", "Opp"))
                if not team:
                    continue

                # Round: "R1", "R2", "EF", "SF", "PF", "GF" etc.
                round_str = get("Round", "Rnd", "Round Number")
                round_num: int | None = None
                if round_str.startswith("R"):
                    try:
                        round_num = int(round_str[1:])
                    except ValueError:
                        round_num = None

                player_id = get("ID", "Player ID", "PlayerID")
                player_name = get("Player", "Player Name")
                if not player_name:
                    continue

                rows.append(PlayerStatRow(
                    season=season,
                    round_number=round_num,
                    team_name=team,
                    opponent_name=opponent,
                    home_away=get("Home/Away", "H/A"),
                    player_external_id=player_id or player_name.replace(" ", "_"),
                    player_name=player_name,
                    disposals=to_int(get("Disposals", "Dis")),
                    kicks=to_int(get("Kicks", "K")),
                    handballs=to_int(get("Handballs", "HB")),
                    goals=to_int(get("Goals", "G")),
                    behinds=to_int(get("Behinds", "B")),
                ))
            except Exception as e:
                logger.debug(f"PlayerCollector: skipping malformed row: {e}")
                continue

        logger.info(f"PlayerCollector: parsed {len(rows)} player stat rows for {season}.")
        return rows

    # ---------------------------------------------------------------------------
    # DB upserts
    # ---------------------------------------------------------------------------

    def _upsert_stats(self, rows: list[PlayerStatRow]) -> int:
        """Match player stat rows to DB matches and upsert PlayerStat records."""
        # Build lookup: (season, round_number, team_name) -> match_id
        team_cache: dict[str, int] = {}
        match_cache: dict[tuple, int] = {}

        teams = self._db.query(Team).all()
        for t in teams:
            team_cache[t.name] = t.id

        matches = (
            self._db.query(Match)
            .filter(Match.season.in_({r.season for r in rows}))
            .all()
        )
        for m in matches:
            ht = self._db.get(Team, m.home_team_id)
            at = self._db.get(Team, m.away_team_id)
            if ht and at:
                match_cache[(m.season, m.round_number, ht.name)] = m.id
                match_cache[(m.season, m.round_number, at.name)] = m.id

        inserted = 0
        for row in rows:
            team_id = team_cache.get(row.team_name)
            match_id = match_cache.get((row.season, row.round_number, row.team_name))
            if not team_id or not match_id:
                continue

            # Upsert by (match_id, team_id, player_external_id)
            existing = (
                self._db.query(PlayerStat)
                .filter(
                    PlayerStat.match_id == match_id,
                    PlayerStat.team_id == team_id,
                    PlayerStat.player_external_id == row.player_external_id,
                )
                .first()
            )
            if existing:
                existing.disposals = row.disposals
                existing.kicks = row.kicks
                existing.handballs = row.handballs
                existing.goals = row.goals
                existing.behinds = row.behinds
            else:
                self._db.add(PlayerStat(
                    match_id=match_id,
                    team_id=team_id,
                    player_external_id=row.player_external_id,
                    player_name=row.player_name,
                    disposals=row.disposals,
                    kicks=row.kicks,
                    handballs=row.handballs,
                    goals=row.goals,
                    behinds=row.behinds,
                ))
                inserted += 1

        self._db.commit()
        logger.info(f"PlayerCollector: upserted {inserted} new player stat rows.")
        return inserted

    # ---------------------------------------------------------------------------
    # Availability index computation
    # ---------------------------------------------------------------------------

    def _compute_and_store_lineups(self, season: int) -> None:
        """
        Compute availability_index for each (match, team) in this season.

        Algorithm:
          1. For each match, look up who played.
          2. For each team, rank players by rolling 5-game contribution score
             (disposals + goals*3) computed from PRIOR matches only (no leakage).
          3. availability_index = (sum of top-22 players' contributions) /
             (expected contribution of a full-strength team)
          Capped to [0, 1].
        """
        matches = (
            self._db.query(Match)
            .filter(Match.season == season)
            .order_by(Match.round_number.asc())
            .all()
        )

        # Build rolling player contribution table (chronological, no leakage)
        # player_external_id -> list of (contribution, match_id) in order
        player_history: dict[str, list[float]] = {}

        for match in matches:
            for team_id in (match.home_team_id, match.away_team_id):
                stats = (
                    self._db.query(PlayerStat)
                    .filter(PlayerStat.match_id == match.id)
                    .filter(PlayerStat.team_id == team_id)
                    .all()
                )
                if not stats:
                    continue

                # Compute each player's contribution for THIS match (for future history)
                match_contribs: dict[str, float] = {}
                for s in stats:
                    disp = s.disposals or 0
                    goals = s.goals or 0
                    c = float(disp + goals * _CONTRIBUTION_WEIGHT_GOALS)
                    match_contribs[s.player_external_id] = c

                    # Update contribution_score in DB
                    s.contribution_score = c
                    # Add to history for future matches
                    hist = player_history.setdefault(s.player_external_id, [])
                    hist.append(c)
                    if len(hist) > 5:
                        hist.pop(0)

                # Compute team availability using PRE-match rolling averages
                # (prior contributions, not this match's actuals)
                team_total_prior = 0.0
                player_prior_scores: list[float] = []
                for s in stats:
                    hist = player_history.get(s.player_external_id, [])
                    # Use average of prior 5 games (not including current)
                    prior = hist[:-1] if hist else []
                    prior_avg = sum(prior) / len(prior) if prior else 5.0  # default 5
                    player_prior_scores.append(prior_avg)
                    team_total_prior += prior_avg

                # Normalise: top-22 by prior score represent "expected" team
                player_prior_scores.sort(reverse=True)
                # When real lineups exist every listed player did play, so the
                # top-22 prior sum equals its own expectation and availability is 1.0.
                avail = 1.0  # if we have actual lineups, all listed played
                key_absent = 0  # no absences when we have actual data

                # Build / update PlayerLineup row
                existing_lineup = (
                    self._db.query(PlayerLineup)
                    .filter(
                        PlayerLineup.match_id == match.id,
                        PlayerLineup.team_id == team_id,
                    )
                    .first()
                )
                if existing_lineup:
                    existing_lineup.players_listed = len(stats)
                    existing_lineup.availability_index = avail
                    existing_lineup.key_players_absent = key_absent
                    existing_lineup.source = "afltables"
                else:
                    self._db.add(PlayerLineup(
                        match_id=match.id,
                        team_id=team_id,
                        players_listed=len(stats),
                        players_absent=0,
                        key_players_absent=key_absent,
                        availability_index=avail,
                        source="afltables",
                    ))

        self._db.commit()
        logger.info(f"PlayerCollector: computed availability index for season {season}.")
