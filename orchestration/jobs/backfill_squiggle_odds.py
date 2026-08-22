"""
orchestration/jobs/backfill_squiggle_odds.py
---------------------------------------------
One-shot job: backfill historical bookmaker consensus odds from the Squiggle
tips API (source=5, "Punters" — punters.com.au bookmaker aggregator).

Why Punters?
  Punters.com.au aggregates real bookmaker H2H prices into a single consensus
  implied probability. The Squiggle tips API exposes this as `hconfidence`
  (home team win % as seen by the market pre-match).  This is the closest
  proxy to bookmaker implied probability available for historical AFL seasons.

Coverage: 2019–2025 (1,400+ games with verified confidence values).
Earlier seasons (2015–2018) use the Squiggle model as fallback if Punters
is unavailable.

Idempotency: safe to re-run — skips any match that already has a
squiggle_punters snapshot.

CLI usage:
    python -m orchestration.jobs.backfill_squiggle_odds
    python -m orchestration.jobs.backfill_squiggle_odds --seasons 2023 2024 2025
    python -m orchestration.jobs.backfill_squiggle_odds --dry-run
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, timedelta

import httpx
from loguru import logger

from db.models.matches import Match
from db.models.odds_snapshots import OddsSnapshot
from db.session import db_session

_SQUIGGLE_URL = "https://api.squiggle.com.au/"
_USER_AGENT = "AFL-predict-research/0.1 (personal research; non-commercial)"

# Punters = bookmaker-consensus source on Squiggle (source id 5).
# Squiggle model (source id 1) used as fallback for seasons with no Punters data.
_PUNTERS_SOURCE_ID = 5
_SQUIGGLE_SOURCE_ID = 1

_BOOKMAKER_KEY = "squiggle_punters"
_BACKFILL_SEASONS = list(range(2015, 2026))  # 2015–2025 inclusive

# Pre-match snapshot offset: store snapshot as 2 hours before match_time
# so BookmakerExtractor (which requires snapshot_time < match_time) picks it up.
_PRE_MATCH_OFFSET = timedelta(hours=2)

# Polite delay between Squiggle API calls
_REQUEST_DELAY = 1.2


def run(seasons: list[int] | None = None, dry_run: bool = False) -> None:
    target_seasons = seasons or _BACKFILL_SEASONS
    logger.info(
        f"==> backfill_squiggle_odds: starting "
        f"(seasons={target_seasons}, dry_run={dry_run})"
    )

    with db_session() as db:
        # Build external_id → match lookup for all target seasons up front
        matches_by_ext_id: dict[str, Match] = {
            m.external_id: m
            for m in db.query(Match).filter(Match.season.in_(target_seasons)).all()
        }
        logger.info(
            f"backfill_squiggle_odds: {len(matches_by_ext_id)} DB matches "
            f"across seasons {target_seasons[0]}–{target_seasons[-1]}"
        )

        # Which match IDs already have a squiggle_punters snapshot?
        existing_ids: set[int] = {
            row.match_id
            for row in db.query(OddsSnapshot.match_id)
            .filter(OddsSnapshot.bookmaker == _BOOKMAKER_KEY)
            .all()
        }
        logger.info(
            f"backfill_squiggle_odds: {len(existing_ids)} matches already have "
            f"a {_BOOKMAKER_KEY!r} snapshot — will skip."
        )

        total_inserted = 0
        total_skipped = 0
        total_no_match = 0

        for season in target_seasons:
            inserted, skipped, no_match = _process_season(
                db, season, matches_by_ext_id, existing_ids, dry_run
            )
            total_inserted += inserted
            total_skipped += skipped
            total_no_match += no_match
            time.sleep(_REQUEST_DELAY)

    logger.info(
        f"==> backfill_squiggle_odds: done — "
        f"{total_inserted} inserted, {total_skipped} already existed, "
        f"{total_no_match} games not in DB."
    )


def _process_season(
    db,
    season: int,
    matches_by_ext_id: dict[str, Match],
    existing_ids: set[int],
    dry_run: bool,
) -> tuple[int, int, int]:
    """Fetch tips for one season and insert snapshots. Returns (inserted, skipped, no_match)."""
    tips = _fetch_tips(season)
    if not tips:
        logger.warning(f"backfill_squiggle_odds: no tips returned for {season}")
        return 0, 0, 0

    # Pick Punters where available, fall back to Squiggle model.
    #
    # These two sources are NOT equivalent: Punters is a bookmaker consensus (a
    # market price), while source 1 is Squiggle's own statistical model (not a
    # market price at all). Silently storing both under one label would make the
    # bookmaker baseline partly a comparison against another model. The source id
    # is therefore persisted per snapshot and the fallback count is logged.
    tips_by_game: dict[int, dict] = {}
    for tip in tips:
        gid = tip["gameid"]
        src = tip.get("sourceid")
        if src == _PUNTERS_SOURCE_ID:
            tips_by_game[gid] = tip  # Punters wins
        elif src == _SQUIGGLE_SOURCE_ID and gid not in tips_by_game:
            tips_by_game[gid] = tip  # Squiggle as fallback

    n_fallback = sum(
        1 for t in tips_by_game.values() if t.get("sourceid") != _PUNTERS_SOURCE_ID
    )
    if n_fallback:
        logger.warning(
            f"backfill_squiggle_odds: {season} — {n_fallback}/{len(tips_by_game)} games "
            "have NO bookmaker consensus and fall back to the Squiggle model "
            "(sourceid=1). Those are model estimates, not market prices; they are "
            "tagged snapshot_type='historical_model' so they can be excluded."
        )

    inserted = skipped = no_match = 0

    for gid, tip in tips_by_game.items():
        hconf = tip.get("hconfidence")
        if not hconf:
            logger.debug(f"backfill_squiggle_odds: gameid={gid} no hconfidence — skip")
            no_match += 1
            continue

        match = matches_by_ext_id.get(str(gid))
        if match is None:
            logger.debug(f"backfill_squiggle_odds: gameid={gid} not in DB — skip")
            no_match += 1
            continue

        if match.id in existing_ids:
            skipped += 1
            continue

        if match.match_time is None:
            logger.debug(
                f"backfill_squiggle_odds: match_id={match.id} has no match_time — skip"
            )
            no_match += 1
            continue

        snapshot = _build_snapshot(match, float(hconf), source_id=tip.get("sourceid"))
        if dry_run:
            logger.info(
                f"[DRY RUN] match_id={match.id} {season} R{tip.get('round')} "
                f"{tip.get('hteam')} vs {tip.get('ateam')} "
                f"home_prob={snapshot.home_implied_prob:.3f}"
            )
        else:
            db.add(snapshot)
            existing_ids.add(match.id)  # prevent double-insert within this run

        inserted += 1

    if not dry_run:
        db.flush()

    logger.info(
        f"backfill_squiggle_odds: {season} — "
        f"{inserted} inserted, {skipped} skipped, {no_match} no DB match, "
        f"{n_fallback} model-estimate fallback "
        f"(from {len(tips_by_game)} unique games)"
    )
    return inserted, skipped, no_match


def _build_snapshot(match: Match, hconfidence: float, source_id: int | None = None) -> OddsSnapshot:
    """
    Build an OddsSnapshot from a Squiggle Punters hconfidence value.

    hconfidence is the home team win % as implied by bookmaker consensus
    (source 5, Punters). It is already overround-normalised (home + away = 100%),
    which means these prices carry NO bookmaker margin — see docs/RESULTS.md
    before treating any simulated return from them as achievable.

    source_id records which Squiggle source the value came from. Anything other
    than Punters is a model estimate rather than a market price and is tagged
    distinctly so downstream analysis can exclude it.
    """
    home_prob = hconfidence / 100.0
    away_prob = 1.0 - home_prob

    # Back-calculate approximate decimal odds (no overround applied — Punters
    # already normalises). These are approximations used only for Kelly sizing.
    home_odds = round(1.0 / home_prob, 3) if home_prob > 0 else None
    away_odds = round(1.0 / away_prob, 3) if away_prob > 0 else None

    # Snapshot time: 2 hours before kickoff so BookmakerExtractor picks it up
    match_time = match.match_time
    if match_time.tzinfo is None:
        match_time = match_time.replace(tzinfo=UTC)
    snapshot_time = match_time - _PRE_MATCH_OFFSET

    return OddsSnapshot(
        match_id=match.id,
        bookmaker=_BOOKMAKER_KEY,
        home_odds=home_odds,
        away_odds=away_odds,
        home_implied_prob=round(home_prob, 6),
        away_implied_prob=round(away_prob, 6),
        overround=1.0,  # Punters normalises to 100%
        snapshot_time=snapshot_time,
        # Both values must fit OddsSnapshot.snapshot_type, which is String(20).
        # 'historical_model_estimate' (25 chars) would be rejected by PostgreSQL,
        # losing exactly the provenance this tag exists to record.
        snapshot_type=(
            "historical_consensus"  # 20 chars
            if source_id == _PUNTERS_SOURCE_ID
            else "historical_model"  # 16 chars
        ),
    )


def _fetch_tips(season: int) -> list[dict]:
    """Fetch all tips for a season from Squiggle, both Punters and Squiggle sources."""
    try:
        r = httpx.get(
            _SQUIGGLE_URL,
            params={"q": "tips", "year": season},
            headers={"User-Agent": _USER_AGENT},
            timeout=30,
            follow_redirects=True,
        )
        r.raise_for_status()
        tips = r.json().get("tips", [])
        # Keep only Punters and Squiggle model sources
        return [t for t in tips if t.get("sourceid") in (_PUNTERS_SOURCE_ID, _SQUIGGLE_SOURCE_ID)]
    except Exception as exc:
        logger.error(f"backfill_squiggle_odds: failed to fetch {season} tips: {exc}")
        return []


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Backfill historical AFL odds from Squiggle Punters tips."
    )
    p.add_argument(
        "--seasons", nargs="+", type=int, help="Seasons to backfill (default: 2015–2025)"
    )
    p.add_argument("--dry-run", action="store_true", help="Log without writing to DB")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    try:
        run(seasons=args.seasons, dry_run=args.dry_run)
    except Exception:
        logger.exception("backfill_squiggle_odds: unhandled error")
        sys.exit(1)
