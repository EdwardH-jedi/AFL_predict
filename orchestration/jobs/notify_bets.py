"""
orchestration/jobs/notify_bets.py
-----------------------------------
Telegram notification job - sends today's value picks as a Telegram message.

Triggered automatically by the daily pipeline after generate_recommendations.
Can also be run manually: python -m orchestration.jobs.notify_bets

Setup:
  1. Create a Telegram bot via @BotFather -> get TELEGRAM_BOT_TOKEN
  2. Start a conversation with your bot or add it to a channel
  3. Get your chat ID from @userinfobot
  4. Add to .env:
       TELEGRAM_BOT_TOKEN=1234567890:AABBccDDeeFF...
       TELEGRAM_CHAT_ID=-100123456789
       TELEGRAM_ENABLED=true

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
  - If TELEGRAM_ENABLED=false or token is blank -> logs and exits silently.
  - Uses httpx (already a project dependency) for the Bot API POST.
  - Max 2 retries with exponential backoff.
  - Returns True on success, False on failure (pipeline treats this as soft).
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone

import httpx
from loguru import logger
from sqlalchemy.orm import Session

from config.settings import get_settings
from db.models.matches import Match
from db.models.predictions import Prediction
from db.models.recommendations import Recommendation
from db.session import SessionLocal

settings = get_settings()

_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
_MAX_RETRIES = 2


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def notify_bets(db: Session | None = None) -> bool:
    """
    Send today's value picks to Telegram.

    Args:
        db: Optional SQLAlchemy Session. If None, a new session is created.

    Returns:
        True if message sent (or notifications disabled).
        False if sending failed after retries.
    """
    if not settings.telegram_enabled:
        logger.info("notify_bets: TELEGRAM_ENABLED=false - skipping notifications.")
        return True

    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        logger.warning(
            "notify_bets: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set - "
            "skipping notifications."
        )
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
    """Load today's pending recommendations with match context."""
    today = date.today()
    start = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
    end = start + timedelta(days=1)

    recs = (
        db.query(Recommendation)
        .filter(Recommendation.status == "pending")
        .filter(Recommendation.created_at >= start)
        .filter(Recommendation.created_at < end)
        .order_by(Recommendation.created_at.asc())
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

        side_prob = (
            pred.home_win_prob if rec.side == "home" else pred.away_win_prob
        )
        picks.append({
            "side": rec.side.upper(),
            "home_team_id": match.home_team_id,
            "away_team_id": match.away_team_id,
            "match_time": match.match_time,
            "odds": rec.recommended_odds,
            "stake_fraction": rec.stake_fraction,
            "stake_dollars": rec.stake_dollars,
            "model_prob": side_prob,
            "paper_trade": rec.paper_trade,
        })

    return picks


def _format_message(picks: list[dict]) -> str:
    """Build the Telegram message string (ASCII-safe for all encodings)."""
    today_str = date.today().strftime("%a %d %b")
    sep = "-" * 24
    mode_label = "Paper trade" if picks[0]["paper_trade"] else "LIVE"

    lines = [
        sep,
        f"[AFL] Value Picks - {today_str}",
        sep,
    ]

    for i, p in enumerate(picks, start=1):
        match_time_str = (
            p["match_time"].strftime("%H:%M AEST")
            if p["match_time"] else "TBC"
        )
        stake_pct = f"{p['stake_fraction'] * 100:.1f}%"
        stake_aud = f" (~${p['stake_dollars']:.0f})" if p["stake_dollars"] else ""
        model_pct = f"{p['model_prob'] * 100:.1f}%" if p["model_prob"] else "N/A"

        if p["side"] == "HOME":
            team_label = f"Home - Team #{p['home_team_id']}"
        else:
            team_label = f"Away - Team #{p['away_team_id']}"

        lines += [
            f"{i}. {p['side']}  {team_label}",
            f"   Kickoff: {match_time_str}",
            f"   Odds: {p['odds']:.2f}  |  Stake: {stake_pct}{stake_aud}",
            f"   Model win prob: {model_pct}",
            "",
        ]

    lines += [
        sep,
        f"{mode_label} - Not financial advice",
    ]

    return "\n".join(lines)


def _send(message: str, attempt: int = 0) -> bool:
    """POST message to Telegram Bot API with retry."""
    url = _TELEGRAM_API.format(token=settings.telegram_bot_token)
    payload = {
        "chat_id": settings.telegram_chat_id,
        "text": message,
        "parse_mode": "HTML",
    }

    try:
        resp = httpx.post(url, json=payload, timeout=15)
        resp.raise_for_status()
        logger.info("notify_bets: Telegram message sent successfully.")
        return True
    except httpx.HTTPStatusError as e:
        logger.error(f"notify_bets: Telegram API error {e.response.status_code}: {e.response.text}")
        if attempt < _MAX_RETRIES:
            import time
            time.sleep(2 ** attempt)
            return _send(message, attempt + 1)
        return False
    except httpx.RequestError as e:
        logger.error(f"notify_bets: Telegram network error: {e}")
        if attempt < _MAX_RETRIES:
            import time
            time.sleep(2 ** attempt)
            return _send(message, attempt + 1)
        return False


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    success = notify_bets()
    sys.exit(0 if success else 1)
