"""
api/routes/discord_history.py
-------------------------------
Read-only API route for Discord bet notification history.

Endpoints:
  GET /discord/history          — parsed bet messages from the Discord channel
  GET /discord/history/raw      — raw message objects (for debugging)
  GET /discord/status           — check if bot token + channel ID are configured
  GET /discord/comparison       — Discord picks vs our Recommendations (agreement + ROI)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from collectors.discord_reader import (
    fetch_all_messages,
    fetch_channel_messages,
    parse_bet_messages,
)
from config.settings import get_settings
from db.models.matches import Match
from db.models.predictions import Prediction
from db.models.recommendations import Recommendation
from db.models.teams import Team
from db.session import get_db

router = APIRouter()
settings = get_settings()


@router.get("/status")
def get_discord_status() -> dict[str, Any]:
    """Check whether the Discord bot is configured and can reach the channel."""
    has_token   = bool(settings.discord_bot_token)
    has_channel = bool(settings.discord_channel_id)
    configured  = has_token and has_channel

    result: dict[str, Any] = {
        "configured": configured,
        "has_bot_token": has_token,
        "has_channel_id": has_channel,
    }

    if configured:
        # Try a minimal fetch (1 message) to verify connectivity
        try:
            msgs = fetch_channel_messages(limit=1)
            result["reachable"] = True
            result["test_message_count"] = len(msgs)
        except Exception as exc:
            result["reachable"] = False
            result["error"] = str(exc)
    else:
        result["reachable"] = False
        result["setup_instructions"] = (
            "Set DISCORD_BOT_TOKEN and DISCORD_CHANNEL_ID in .env. "
            "See .env.example for setup steps."
        )

    return result


@router.get("/history")
def get_discord_history(
    limit: int = Query(default=200, ge=1, le=500),
) -> dict[str, Any]:
    """
    Fetch and parse AFL bet notification messages from the Discord channel.

    Returns structured bet records extracted from the message text.
    Messages that don't match the AFL notification format are ignored.

    Args:
        limit: Max total messages to fetch from Discord (1–500).
    """
    raw = fetch_all_messages(max_messages=limit)
    parsed = parse_bet_messages(raw)

    # Summary stats across all parsed messages
    total_bets = sum(len(m["bets"]) for m in parsed)
    dates = sorted({m["date_label"] for m in parsed})

    return {
        "messages_fetched": len(raw),
        "afl_notifications": len(parsed),
        "total_picks": total_bets,
        "date_range": {
            "first": dates[0] if dates else None,
            "last": dates[-1] if dates else None,
        },
        "history": parsed,  # newest last (chronological)
    }


@router.get("/history/raw")
def get_discord_history_raw(
    limit: int = Query(default=50, ge=1, le=100),
) -> dict[str, Any]:
    """
    Return raw Discord message objects — useful for debugging parser issues.
    Only returns messages that contain an AFL notification header.
    """
    raw = fetch_channel_messages(limit=limit)
    afl_only = [
        {
            "id":        m.get("id"),
            "timestamp": m.get("timestamp"),
            "author":    m.get("author", {}).get("username"),
            "content":   m.get("content", "")[:500],  # truncate for safety
        }
        for m in raw
        if "[AFL]" in m.get("content", "")
    ]
    return {"raw_count": len(raw), "afl_count": len(afl_only), "messages": afl_only}


# ---------------------------------------------------------------------------
# Comparison: Discord picks vs our Recommendations
# ---------------------------------------------------------------------------

@router.get("/comparison")
def get_discord_comparison(
    limit: int = Query(default=300, ge=50, le=500),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Join Discord tips to our own Recommendations by team + nearby match date.

    Returns:
      summary          agreement %, disagreement %, unmatched count, ROI-when-disagree
      per_author       per-tipster tally of n, agree, win rate on matched + settled picks
      disagreements    picks where we backed the opposite side — the interesting subset
    """
    if not (settings.discord_bot_token and settings.discord_channel_id):
        return {"available": False, "reason": "Discord bot not configured."}

    # 1. Pull Discord picks
    try:
        raw = fetch_all_messages(max_messages=limit)
        parsed = parse_bet_messages(raw)
    except Exception as exc:
        return {"available": False, "reason": f"Discord fetch failed: {exc}"}

    # 2. Build team name → id map (tolerant lookup)
    teams: dict[str, int] = {}
    for t in db.query(Team).all():
        teams[t.name.lower()] = t.id
        teams[t.short_name.lower()] = t.id

    # 3. Flatten to rows, one per pick
    matched: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []

    for msg in parsed:
        sent_at_iso = msg.get("sent_at") or ""
        sent_dt: datetime | None = None
        try:
            sent_dt = datetime.fromisoformat(sent_at_iso.replace("Z", "+00:00"))
            if sent_dt.tzinfo is None:
                sent_dt = sent_dt.replace(tzinfo=UTC)
        except Exception:
            sent_dt = None

        for bet in msg.get("bets", []):
            pick_id = teams.get(bet["pick_team"].lower())
            opp_id = teams.get(bet["opp_team"].lower())
            if pick_id is None or opp_id is None or sent_dt is None:
                unmatched.append({**bet, "reason": "team or timestamp lookup failed",
                                  "author": msg.get("author"), "sent_at": sent_at_iso})
                continue

            match = _find_match(db, pick_id, opp_id, sent_dt)
            if match is None:
                unmatched.append({**bet, "reason": "no Match within ±4 days",
                                  "author": msg.get("author"), "sent_at": sent_at_iso})
                continue

            # Our side in this match (home or away based on pick_id vs match home_team)
            our_rec = _our_recommendation(db, match.id)
            agree: bool | None
            our_side = our_rec.side if our_rec else None
            discord_side_vs_match = (
                "home" if pick_id == match.home_team_id else "away"
            )
            if our_rec is None:
                agree = None  # we didn't bet at all
            else:
                agree = our_rec.side == discord_side_vs_match

            outcome_dict: dict[str, Any] | None = None
            if our_rec and our_rec.bet_outcome:
                out = our_rec.bet_outcome
                outcome_dict = {
                    "won": out.won,
                    "pl_units": out.profit_loss_units,
                    "clv": out.clv,
                }

            matched.append({
                "sent_at": sent_at_iso,
                "author": msg.get("author"),
                "mode": msg.get("mode"),
                "pick_team": bet["pick_team"],
                "opp_team": bet["opp_team"],
                "discord_side": discord_side_vs_match,
                "discord_odds": bet.get("odds"),
                "discord_edge": bet.get("edge"),
                "discord_stake_pct": bet.get("stake_pct"),
                "our_side": our_side,
                "our_odds": our_rec.recommended_odds if our_rec else None,
                "our_stake_fraction": our_rec.stake_fraction if our_rec else None,
                "agree": agree,
                "match_id": match.id,
                "match_time": match.match_time.isoformat() if match.match_time else None,
                "match_result": match.result,
                "outcome": outcome_dict,
            })

    # 4. Summary stats
    n_matched = len(matched)
    n_agree = sum(1 for r in matched if r["agree"] is True)
    n_disagree = sum(1 for r in matched if r["agree"] is False)
    n_we_didnt_bet = sum(1 for r in matched if r["agree"] is None)

    # ROI when we disagree, computed on OUR settled bets in that subset
    disagree_settled = [r for r in matched if r["agree"] is False and r["outcome"]]
    our_pl = sum((r["outcome"]["pl_units"] or 0.0) for r in disagree_settled)
    our_stake = sum((r["our_stake_fraction"] or 0.0) for r in disagree_settled)
    roi_disagree = (our_pl / our_stake) if our_stake > 0 else None

    # Per-author leaderboard
    by_author: dict[str, dict[str, Any]] = {}
    for r in matched:
        a = r["author"] or "unknown"
        slot = by_author.setdefault(a, {"n": 0, "agree": 0, "disagree": 0, "settled": 0, "wins": 0})
        slot["n"] += 1
        if r["agree"] is True:
            slot["agree"] += 1
        elif r["agree"] is False:
            slot["disagree"] += 1
        # "wins" here = did DISCORD's pick side actually win?
        if r["match_result"] in ("home", "away"):
            slot["settled"] += 1
            if r["match_result"] == r["discord_side"]:
                slot["wins"] += 1

    per_author = [
        {
            "author": a,
            **slot,
            "discord_hit_rate": round(slot["wins"] / slot["settled"], 4)
                if slot["settled"] else None,
            "agreement_rate": round(slot["agree"] / slot["n"], 4) if slot["n"] else None,
        }
        for a, slot in by_author.items()
    ]
    per_author.sort(key=lambda r: (r["discord_hit_rate"] or -1), reverse=True)

    return {
        "available": True,
        "summary": {
            "n_discord_picks": sum(len(m["bets"]) for m in parsed),
            "n_matched": n_matched,
            "n_unmatched": len(unmatched),
            "n_agree": n_agree,
            "n_disagree": n_disagree,
            "n_we_didnt_bet": n_we_didnt_bet,
            "agreement_rate": round(n_agree / n_matched, 4) if n_matched else None,
            "roi_when_disagree": round(roi_disagree, 4) if roi_disagree is not None else None,
            "n_disagree_settled": len(disagree_settled),
        },
        "per_author": per_author,
        "disagreements": [r for r in matched if r["agree"] is False][:100],
        "unmatched_sample": unmatched[:20],
    }


def _find_match(db: Session, team_a_id: int, team_b_id: int, near: datetime) -> Match | None:
    """Find the Match between team_a and team_b within ±4 days of `near`."""
    window_start = near - timedelta(days=4)
    window_end = near + timedelta(days=4)
    return (
        db.query(Match)
        .filter(Match.match_time.isnot(None))
        .filter(Match.match_time >= window_start)
        .filter(Match.match_time <= window_end)
        .filter(
            ((Match.home_team_id == team_a_id) & (Match.away_team_id == team_b_id))
            | ((Match.home_team_id == team_b_id) & (Match.away_team_id == team_a_id))
        )
        .order_by(Match.match_time.asc())
        .first()
    )


def _our_recommendation(db: Session, match_id: int) -> Recommendation | None:
    """Return our latest Recommendation for this match, if any."""
    return (
        db.query(Recommendation)
        .join(Prediction, Recommendation.prediction_id == Prediction.id)
        .filter(Prediction.match_id == match_id)
        .order_by(Recommendation.created_at.desc())
        .first()
    )
