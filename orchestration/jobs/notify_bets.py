"""
orchestration/jobs/notify_bets.py
-----------------------------------
Discord notification job - sends today's value picks as a Discord message.

Triggered automatically by the daily pipeline after generate_recommendations.
Can also be run manually: python -m orchestration.jobs.notify_bets

Setup:
  1. Discord 채널 설정 -> 연동 -> 웹후크 -> 새 웹후크 -> URL 복사
  2. Add to .env:
       DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
       DISCORD_ENABLED=true

Message format (example):
  ------------------------
  [AFL] Value Picks - Mon 7 Apr
  ------------------------
  1. HOME  Richmond Tigers
     Odds: 2.15  |  Edge: +5.2%
     Stake: 3.1% bankroll (~$31)
     Model: 54.1% win prob

Design:
  - Reads today's pending recommendations from the DB.
  - If DISCORD_ENABLED=false or webhook URL is blank -> logs and exits silently.
  - Uses httpx (already a project dependency) for the webhook POST.
  - Max 2 retries with exponential backoff.
  - Returns True on success, False on failure (pipeline treats this as soft).
"""

from __future__ import annotations

import sys
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from loguru import logger
from sqlalchemy.orm import Session

from config.settings import get_settings
from db.models.matches import Match
from db.models.predictions import Prediction
from db.models.recommendations import Recommendation
from db.models.teams import Team
from db.session import SessionLocal

_AEST = ZoneInfo("Australia/Sydney")

settings = get_settings()

_MAX_RETRIES = 2


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def notify_bets(db: Session | None = None) -> bool:
    """
    Send today's value picks to Discord.

    Args:
        db: Optional SQLAlchemy Session. If None, a new session is created.

    Returns:
        True if message sent (or notifications disabled).
        False if sending failed after retries.
    """
    if not settings.discord_enabled:
        logger.info("notify_bets: DISCORD_ENABLED=false - skipping notifications.")
        return True

    if not settings.discord_webhook_url:
        logger.warning("notify_bets: DISCORD_WEBHOOK_URL not set - skipping notifications.")
        return True

    own_session = db is None
    if own_session:
        db = SessionLocal()

    try:
        picks = _load_todays_picks(db)
        if not picks:
            logger.info("notify_bets: no picks for today - nothing to send.")
            return True

        message = _format_message(picks)
        return _send(message)
    finally:
        if own_session:
            db.close()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_todays_picks(db: Session) -> list[dict]:
    """Load pending recommendations for matches happening today (by match_time)."""
    today = date.today()
    start = datetime(today.year, today.month, today.day, tzinfo=UTC)
    end = start + timedelta(days=1)

    recs = (
        db.query(Recommendation)
        .join(Prediction, Prediction.id == Recommendation.prediction_id)
        .join(Match, Match.id == Prediction.match_id)
        .filter(Recommendation.status == "pending")
        .filter(Match.match_time >= start)
        .filter(Match.match_time < end)
        .order_by(Match.match_time.asc())
        .all()
    )

    picks: list[dict] = []
    for rec in recs:
        pred: Prediction | None = db.get(Prediction, rec.prediction_id)
        if pred is None:
            continue
        match: Match | None = db.get(Match, pred.match_id)
        if match is None:
            continue

        home_team: Team | None = db.get(Team, match.home_team_id)
        away_team: Team | None = db.get(Team, match.away_team_id)

        is_home = rec.side == "home"
        side_prob = pred.home_win_prob if is_home else pred.away_win_prob
        edge = pred.home_edge if is_home else pred.away_edge
        bm_implied = (side_prob - edge) if (side_prob is not None and edge is not None) else None

        picks.append(
            {
                "side": rec.side.upper(),
                "pick_team": home_team.name
                if (is_home and home_team)
                else (away_team.name if away_team else "Unknown"),
                "opp_team": away_team.name
                if (is_home and away_team)
                else (home_team.name if home_team else "Unknown"),
                "is_home": is_home,
                "match_time": match.match_time,
                "round_label": match.round_label,
                "odds": rec.recommended_odds,
                "stake_fraction": rec.stake_fraction,
                "stake_dollars": rec.stake_dollars,
                "model_prob": side_prob,
                "bm_implied": bm_implied,
                "edge": edge,
                "paper_trade": rec.paper_trade,
            }
        )

    return picks


def _format_message(picks: list[dict]) -> str:
    """Build the Discord message string."""
    today_str = date.today().strftime("%a %d %b")
    sep = "=" * 32
    mode_label = "PAPER TRADE" if picks[0]["paper_trade"] else "LIVE"

    lines = [
        "```",
        sep,
        f"[AFL] Value Picks - {today_str}  ({mode_label})",
        sep,
    ]

    for i, p in enumerate(picks, start=1):
        # Match time in AEST
        if p["match_time"]:
            mt = p["match_time"]
            if mt.tzinfo is None:
                mt = mt.replace(tzinfo=UTC)
            mt_aest = mt.astimezone(_AEST)
            match_time_str = mt_aest.strftime("%a %d %b %I:%M%p")
        else:
            match_time_str = "TBC"

        venue_str = "HOME" if p["is_home"] else "AWAY"
        round_str = p.get("round_label") or ""

        model_pct = f"{p['model_prob'] * 100:.0f}%" if p["model_prob"] is not None else "N/A"
        mkt_pct   = f"{p['bm_implied'] * 100:.0f}%" if p["bm_implied"] is not None else "N/A"
        edge_pct  = f"{p['edge'] * 100:+.0f}%"      if p["edge"] is not None else "N/A"
        stake_pct = f"{p['stake_fraction'] * 100:.1f}%"
        strength  = _edge_label(p["edge"])

        lines += [
            f"{i}. {p['pick_team']} ({venue_str}) vs {p['opp_team']}",
            f"   {round_str} | {match_time_str} | @ {p['odds']:.2f}",
            f"   Model {model_pct} vs Mkt {mkt_pct} | Edge {edge_pct} | Stake {stake_pct}",
            f"   >> {strength}: ELO/form rates {p['pick_team']} higher than market.",
            "",
        ]

    lines += [
        sep,
        "Not financial advice.",
        "```",
    ]

    return "\n".join(lines)


def _edge_label(edge: float | None) -> str:
    if edge is None:
        return "Value"
    pct = edge * 100
    if pct >= 12:
        return "Strong value"
    if pct >= 6:
        return "Clear value"
    return "Moderate value"


def _send(message: str, attempt: int = 0) -> bool:
    """POST message to Discord webhook with retry."""
    payload = {"content": message}

    try:
        resp = httpx.post(settings.discord_webhook_url, json=payload, timeout=15)
        resp.raise_for_status()
        logger.info("notify_bets: Discord message sent successfully.")
        return True
    except httpx.HTTPStatusError as e:
        logger.error(f"notify_bets: Discord API error {e.response.status_code}: {e.response.text}")
        if attempt < _MAX_RETRIES:
            import time
            time.sleep(2 ** attempt)
            return _send(message, attempt + 1)
        return False
    except httpx.RequestError as e:
        logger.error(f"notify_bets: Discord network error: {e}")
        if attempt < _MAX_RETRIES:
            import time
            time.sleep(2 ** attempt)
            return _send(message, attempt + 1)
        return False


# ---------------------------------------------------------------------------
# Pipeline entry point (called by orchestration/pipeline_state.py)
# ---------------------------------------------------------------------------

def run() -> None:
    """Pipeline-compatible entry point. Raises on failure so the job is marked failed."""
    success = notify_bets()
    if not success:
        raise RuntimeError("notify_bets: failed to send Discord message after retries.")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    success = notify_bets()
    sys.exit(0 if success else 1)
