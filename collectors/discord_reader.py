"""
collectors/discord_reader.py
-----------------------------
Read bet notification messages from a Discord channel via the Discord REST API.

Requires:
  DISCORD_BOT_TOKEN   — bot token (NOT a webhook URL)
  DISCORD_CHANNEL_ID  — numeric ID of the channel containing bet notifications

The bot must have:
  - Read Messages / View Channel
  - Read Message History
  - (optionally) Message Content Intent enabled in the Dev Portal

Usage:
  from collectors.discord_reader import fetch_channel_messages, parse_bet_messages

  raw     = fetch_channel_messages(limit=50)   # list of raw Discord message dicts
  parsed  = parse_bet_messages(raw)             # list of structured bet-day dicts
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

import httpx
from loguru import logger

from config.settings import get_settings

_DISCORD_API = "https://discord.com/api/v10"
_MAX_LIMIT = 100  # Discord API ceiling per request

settings = get_settings()


# ---------------------------------------------------------------------------
# Fetch raw messages from Discord
# ---------------------------------------------------------------------------

def fetch_channel_messages(
    limit: int = 100,
    before: str | None = None,
    after: str | None = None,
) -> list[dict[str, Any]]:
    """
    Fetch up to `limit` messages from the configured Discord channel.

    Args:
        limit:  Max messages to return (1–100, Discord API ceiling).
        before: Snowflake ID — return messages before this ID (for pagination).
        after:  Snowflake ID — return messages after this ID.

    Returns:
        List of raw Discord message objects (dicts), newest-first.
        Empty list if bot token / channel ID not configured.
    """
    token = settings.discord_bot_token
    channel_id = settings.discord_channel_id

    if not token or not channel_id:
        logger.warning(
            "discord_reader: DISCORD_BOT_TOKEN or DISCORD_CHANNEL_ID not set. "
            "Returning empty message list."
        )
        return []

    limit = max(1, min(limit, _MAX_LIMIT))
    params: dict[str, Any] = {"limit": limit}
    if before:
        params["before"] = before
    if after:
        params["after"] = after

    url = f"{_DISCORD_API}/channels/{channel_id}/messages"
    headers = {"Authorization": f"Bot {token}"}

    try:
        resp = httpx.get(url, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        messages = resp.json()
        logger.info(f"discord_reader: fetched {len(messages)} messages from channel {channel_id}")
        return messages
    except httpx.HTTPStatusError as e:
        logger.error(
            f"discord_reader: HTTP {e.response.status_code} — {e.response.text}"
        )
        return []
    except httpx.RequestError as e:
        logger.error(f"discord_reader: network error — {e}")
        return []


def fetch_all_messages(max_messages: int = 500) -> list[dict[str, Any]]:
    """
    Fetch up to `max_messages` messages, paginating with `before` if needed.

    Returns all messages sorted oldest-first.
    """
    all_msgs: list[dict[str, Any]] = []
    before: str | None = None
    per_page = _MAX_LIMIT

    while len(all_msgs) < max_messages:
        batch = fetch_channel_messages(limit=per_page, before=before)
        if not batch:
            break
        all_msgs.extend(batch)
        if len(batch) < per_page:
            break  # no more pages
        before = batch[-1]["id"]  # oldest in batch → fetch earlier messages next

    # Discord returns newest-first per page; reverse to get chronological order
    all_msgs.reverse()
    return all_msgs[:max_messages]


# ---------------------------------------------------------------------------
# Parse structured bet data from message content
# ---------------------------------------------------------------------------

# Patterns that identify an AFL bet notification block
_HEADER_RE = re.compile(
    r"\[AFL\]\s+Value Picks\s*[-–]\s*(.+?)\s+\((PAPER TRADE|LIVE)\)", re.IGNORECASE
)
_BET_LINE_RE = re.compile(
    r"(\d+)\.\s+(.+?)\s+\((HOME|AWAY)\)\s+vs\s+(.+)"
)
_ODDS_LINE_RE = re.compile(
    r"@\s*([\d.]+)"
)
_MODEL_EDGE_RE = re.compile(
    r"Model\s+([\d.]+)%.*?Mkt\s+([\d.]+)%.*?Edge\s+([+-][\d.]+)%.*?Stake\s+([\d.]+)%",
    re.IGNORECASE,
)
_ROUND_RE = re.compile(r"(R\d+|Round\s*\d+|Finals?|GF|Semi|Prelim|Elim)", re.IGNORECASE)


def parse_bet_messages(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Parse raw Discord message objects and extract structured bet-day records.

    Each output record represents one daily bet notification message:
    {
        "message_id":  Discord snowflake ID (str)
        "sent_at":     ISO timestamp (UTC)
        "date_label":  e.g. "Mon 7 Apr"
        "mode":        "PAPER TRADE" | "LIVE"
        "author":      Discord username
        "bets": [
            {
                "pick_team":  str
                "opp_team":   str
                "side":       "home" | "away"
                "odds":       float | None
                "round":      str | None
                "model_prob": float | None   (0–1)
                "mkt_prob":   float | None
                "edge":       float | None   (can be negative)
                "stake_pct":  float | None   (0–1)
            },
            ...
        ]
    }

    Non-AFL messages (no header match) are silently skipped.
    """
    results: list[dict[str, Any]] = []

    for msg in messages:
        content: str = msg.get("content", "")
        if not content:
            continue

        # Check for AFL bet notification header
        header_m = _HEADER_RE.search(content)
        if not header_m:
            continue

        date_label = header_m.group(1).strip()
        mode = header_m.group(2).upper()

        sent_at_raw = msg.get("timestamp", "")
        try:
            sent_at = datetime.fromisoformat(
                sent_at_raw.replace("Z", "+00:00")
            ).astimezone(UTC).isoformat()
        except (ValueError, AttributeError):
            sent_at = sent_at_raw

        author = ""
        if msg.get("author"):
            author = msg["author"].get("username", "")

        bets: list[dict[str, Any]] = []
        lines = content.split("\n")
        i = 0
        while i < len(lines):
            line = lines[i]
            bet_m = _BET_LINE_RE.search(line)
            if bet_m:
                pick_team = bet_m.group(2).strip()
                side_raw  = bet_m.group(3).upper()
                opp_team  = bet_m.group(4).strip()
                side = "home" if side_raw == "HOME" else "away"

                # Next line: round | match_time | @ odds
                odds: float | None = None
                round_label: str | None = None
                if i + 1 < len(lines):
                    next_line = lines[i + 1]
                    odds_m = _ODDS_LINE_RE.search(next_line)
                    if odds_m:
                        try:
                            odds = float(odds_m.group(1))
                        except ValueError:
                            pass
                    round_m = _ROUND_RE.search(next_line)
                    if round_m:
                        round_label = round_m.group(0).strip()

                # Line after that: Model X% vs Mkt X% | Edge X% | Stake X%
                model_prob = mkt_prob = edge = stake_pct = None
                if i + 2 < len(lines):
                    stat_line = lines[i + 2]
                    stat_m = _MODEL_EDGE_RE.search(stat_line)
                    if stat_m:
                        try:
                            model_prob = float(stat_m.group(1)) / 100
                            mkt_prob   = float(stat_m.group(2)) / 100
                            edge       = float(stat_m.group(3)) / 100
                            stake_pct  = float(stat_m.group(4)) / 100
                        except ValueError:
                            pass

                bets.append({
                    "pick_team":  pick_team,
                    "opp_team":   opp_team,
                    "side":       side,
                    "odds":       odds,
                    "round":      round_label,
                    "model_prob": model_prob,
                    "mkt_prob":   mkt_prob,
                    "edge":       edge,
                    "stake_pct":  stake_pct,
                })
            i += 1

        results.append({
            "message_id": msg.get("id", ""),
            "sent_at":    sent_at,
            "date_label": date_label,
            "mode":       mode,
            "author":     author,
            "bets":       bets,
        })

    return results
