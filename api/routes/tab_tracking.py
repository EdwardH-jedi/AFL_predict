"""
api/routes/tab_tracking.py
---------------------------
TAB live-bet recording and paper-vs-live comparison API.

Endpoints:
  POST /api/tab/record-bet        — record a bet placed at the TAB counter
  POST /api/tab/settle-bet/{id}   — settle a TAB bet with result and payout
  GET  /api/tab/comparison        — paper-trade vs live ROI / odds slippage comparison
  GET  /api/tab/today             — today's picks (mobile brief before going to TAB)

Design notes:
  - TAB live bets are stored in bet_outcomes with bet_source='tab_live'.
  - Each live bet is auto-matched to the closest paper-trade Recommendation
    (same match + side) for odds slippage tracking. Match is by query at
    record time — no FK enforced (TAB bets stand alone if no recommendation exists).
  - Two separate BankrollLog streams: log_type='paper' and log_type='live'.
  - Paper bankroll starts at $1000 (virtual). Live bankroll starts from first deposit.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, status
from loguru import logger
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from api.dependencies import DbSession
from config.settings import get_settings
from db.models.bankroll_logs import BankrollLog
from db.models.bet_outcomes import BetOutcome
from db.models.matches import Match
from db.models.predictions import Prediction
from db.models.recommendations import Recommendation
from db.models.teams import Team

settings = get_settings()
router = APIRouter()

_PAPER_INITIAL = 1000.0   # Simulated paper bankroll starting value


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class RecordBetRequest(BaseModel):
    match_id: int
    bet_side: str = Field(..., pattern="^(home|away)$")
    stake_amount: float = Field(..., gt=0, description="AUD stake placed at TAB counter")
    actual_odds: float = Field(..., gt=1.0, description="Decimal odds received at TAB")
    placed_at: datetime | None = Field(
        default=None,
        description="When the bet was placed (ISO-8601). Defaults to now.",
    )

    @field_validator("stake_amount", "actual_odds")
    @classmethod
    def _finite_positive(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("Value must be a finite number.")
        return round(v, 4)


class RecordBetResponse(BaseModel):
    bet_id: int
    match_id: int
    bet_side: str
    stake_amount_aud: float
    actual_tab_odds: float
    recommended_odds: float | None
    odds_slippage: float | None
    live_bankroll_after: float
    matched_recommendation_id: int | None


class SettleBetRequest(BaseModel):
    result: str = Field(..., pattern="^(win|loss)$")
    payout_amount: float | None = Field(
        default=None,
        ge=0,
        description=(
            "Total AUD payout received from TAB (stake + winnings on win, 0 on loss). "
            "Computed automatically if omitted: stake × actual_odds on win, 0 on loss."
        ),
    )


class SettleBetResponse(BaseModel):
    bet_id: int
    won: bool
    profit_loss_aud: float
    payout_amount_aud: float
    live_bankroll_after: float


# ---------------------------------------------------------------------------
# POST /api/tab/record-bet
# ---------------------------------------------------------------------------

@router.post(
    "/record-bet",
    response_model=RecordBetResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record a bet placed at the TAB counter",
)
def record_bet(body: RecordBetRequest, db: DbSession) -> RecordBetResponse:
    """
    Record a live TAB bet and auto-match it to the model's recommendation.

    Steps:
      1. Validate the match exists.
      2. Find the latest paper-trade recommendation for this match + side.
      3. Compute odds slippage (actual_odds - recommended_odds).
      4. Create a BetOutcome row (bet_source='tab_live').
      5. Debit the live bankroll by stake_amount (bet_placed log entry).
    """
    match = db.get(Match, body.match_id)
    if match is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Match {body.match_id} not found.",
        )

    placed_at = body.placed_at or datetime.now(tz=UTC)

    # Auto-match to paper-trade recommendation (same match + side)
    matched_rec: Recommendation | None = (
        db.query(Recommendation)
        .join(Prediction, Prediction.id == Recommendation.prediction_id)
        .filter(
            Prediction.match_id == body.match_id,
            Recommendation.side == body.bet_side,
        )
        .order_by(Recommendation.created_at.desc())
        .first()
    )

    rec_odds: float | None = matched_rec.recommended_odds if matched_rec else None
    slippage: float | None = (
        round(body.actual_odds - rec_odds, 4) if rec_odds is not None else None
    )

    # Current live bankroll before this bet
    live_balance_before = _latest_balance(db, "live")
    if live_balance_before is None:
        # First live bet — initialise from settings or default
        live_balance_before = settings.live_initial_bankroll

    # Create BetOutcome
    outcome = BetOutcome(
        recommendation_id=None,
        match_id=body.match_id,
        bet_side=body.bet_side,
        bet_source="tab_live",
        actual_tab_odds=body.actual_odds,
        recommended_odds=rec_odds,
        odds_slippage=slippage,
        stake_amount_aud=body.stake_amount,
        stake_fraction=matched_rec.stake_fraction if matched_rec else None,
        placed_at=placed_at,
    )
    db.add(outcome)
    db.flush()

    # Debit live bankroll
    balance_after = round(live_balance_before - body.stake_amount, 4)
    note = (
        f"TAB bet: match {body.match_id} {body.bet_side} @ {body.actual_odds}"
        + (f" | slippage {slippage:+.3f}" if slippage is not None else "")
    )
    db.add(BankrollLog(
        log_type="live",
        event_type="bet_placed",
        balance_after=balance_after,
        amount=-body.stake_amount,
        recommendation_id=outcome.id,
        note=note,
    ))

    logger.info(
        f"TAB bet recorded: id={outcome.id} match={body.match_id} "
        f"side={body.bet_side} stake=${body.stake_amount:.2f} "
        f"@ {body.actual_odds} slippage={slippage}"
    )

    return RecordBetResponse(
        bet_id=outcome.id,
        match_id=body.match_id,
        bet_side=body.bet_side,
        stake_amount_aud=body.stake_amount,
        actual_tab_odds=body.actual_odds,
        recommended_odds=rec_odds,
        odds_slippage=slippage,
        live_bankroll_after=balance_after,
        matched_recommendation_id=matched_rec.id if matched_rec else None,
    )


# ---------------------------------------------------------------------------
# POST /api/tab/settle-bet/{bet_id}
# ---------------------------------------------------------------------------

@router.post(
    "/settle-bet/{bet_id}",
    response_model=SettleBetResponse,
    summary="Settle a TAB bet with the actual result",
)
def settle_bet(bet_id: int, body: SettleBetRequest, db: DbSession) -> SettleBetResponse:
    """
    Mark a previously recorded TAB bet as won or lost and update the live bankroll.

    The stake was debited from the live bankroll at record time.
    Settlement credits back the payout (0 on loss, stake × odds on win).
    """
    outcome = db.get(BetOutcome, bet_id)
    if outcome is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"BetOutcome {bet_id} not found.",
        )
    if outcome.bet_source != "tab_live":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Bet {bet_id} is a paper-trade record. "
                "Use settle_results pipeline job instead."
            ),
        )
    if outcome.won is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Bet {bet_id} already settled (won={outcome.won}).",
        )

    won = body.result == "win"
    stake = outcome.stake_amount_aud or 0.0
    odds  = outcome.actual_tab_odds or 1.0

    if body.payout_amount is not None:
        payout = body.payout_amount
    else:
        payout = round(stake * odds, 4) if won else 0.0

    profit = round(payout - stake, 4)

    # Kelly-unit profit/loss for comparison with paper metrics
    sf = outcome.stake_fraction
    pl_units = (
        round(sf * (odds - 1.0), 6) if (won and sf is not None)
        else (round(-sf, 6) if sf is not None else None)
    )

    outcome.won = won
    outcome.payout_amount_aud = payout
    outcome.profit_loss_dollars = profit
    outcome.profit_loss_units = pl_units
    outcome.settled_at = datetime.now(tz=UTC)

    # Credit live bankroll with payout
    live_balance_before = _latest_balance(db, "live") or 0.0
    balance_after = round(live_balance_before + payout, 4)
    db.add(BankrollLog(
        log_type="live",
        event_type="bet_settled",
        balance_after=balance_after,
        amount=payout,
        recommendation_id=bet_id,
        note=(
            f"TAB {'WIN' if won else 'LOSS'}: bet {bet_id} "
            f"payout=${payout:.2f} profit={profit:+.2f}"
        ),
    ))

    logger.info(
        f"TAB bet settled: id={bet_id} won={won} "
        f"payout=${payout:.2f} profit={profit:+.2f} bankroll→${balance_after:.2f}"
    )

    return SettleBetResponse(
        bet_id=bet_id,
        won=won,
        profit_loss_aud=profit,
        payout_amount_aud=payout,
        live_bankroll_after=balance_after,
    )


# ---------------------------------------------------------------------------
# GET /api/tab/comparison
# ---------------------------------------------------------------------------

@router.get("/comparison", summary="Paper-trade vs live TAB comparison")
def get_comparison(db: DbSession) -> dict[str, Any]:
    """
    Side-by-side performance comparison: paper-trade model vs live TAB bets.

    Returns:
      - paper: ROI, hit rate, cumulative profit, bankroll
      - live:  ROI, hit rate, cumulative profit (AUD), bankroll
      - odds_slippage: distribution of actual vs recommended odds
      - bankroll_curves: time series for both streams (chart data)
      - recent_live_bets: last 20 TAB bets for quick review
    """
    # Paper settled outcomes
    paper_settled = (
        db.query(BetOutcome)
        .filter(BetOutcome.bet_source == "paper", BetOutcome.won.isnot(None))
        .order_by(BetOutcome.settled_at.asc())
        .all()
    )
    paper_stats = _compute_outcome_stats(paper_settled, use_units=True)
    paper_balance = _latest_balance(db, "paper") or _PAPER_INITIAL

    # Live settled outcomes
    live_settled = (
        db.query(BetOutcome)
        .filter(BetOutcome.bet_source == "tab_live", BetOutcome.won.isnot(None))
        .order_by(BetOutcome.settled_at.asc())
        .all()
    )
    live_stats = _compute_outcome_stats(live_settled, use_units=False)
    live_balance = _latest_balance(db, "live")

    # Odds slippage distribution (all TAB bets with both odds values)
    slippage_bets = (
        db.query(BetOutcome)
        .filter(
            BetOutcome.bet_source == "tab_live",
            BetOutcome.actual_tab_odds.isnot(None),
            BetOutcome.recommended_odds.isnot(None),
        )
        .all()
    )
    slippages = [o.odds_slippage for o in slippage_bets if o.odds_slippage is not None]
    rec_odds_list = [o.recommended_odds for o in slippage_bets if o.recommended_odds]
    tab_odds_list = [o.actual_tab_odds for o in slippage_bets if o.actual_tab_odds]

    slippage_summary: dict[str, Any] = {"n_bets_with_slippage": len(slippages)}
    if slippages:
        slippage_summary.update({
            "mean":            round(sum(slippages) / len(slippages), 4),
            "min":             round(min(slippages), 4),
            "max":             round(max(slippages), 4),
            "pct_better_than_recommended": round(
                sum(1 for s in slippages if s > 0) / len(slippages) * 100, 1
            ),
            "avg_recommended_odds": (
                round(sum(rec_odds_list) / len(rec_odds_list), 4)
                if rec_odds_list else None
            ),
            "avg_tab_odds": (
                round(sum(tab_odds_list) / len(tab_odds_list), 4)
                if tab_odds_list else None
            ),
        })

    # Bankroll curves (up to 500 entries each)
    def _curve(log_type: str) -> list[dict]:
        logs = (
            db.query(BankrollLog)
            .filter(BankrollLog.log_type == log_type)
            .order_by(BankrollLog.created_at.asc())
            .limit(500)
            .all()
        )
        return [
            {
                "at":      log.created_at.isoformat() if log.created_at else None,
                "balance": round(log.balance_after, 4),
                "event":   log.event_type,
            }
            for log in logs
        ]

    # Recent live bets (last 20, for display)
    recent = (
        db.query(BetOutcome)
        .filter(BetOutcome.bet_source == "tab_live")
        .order_by(BetOutcome.placed_at.desc().nullsfirst())
        .limit(20)
        .all()
    )

    return {
        "paper": {
            **paper_stats,
            "current_bankroll":  round(paper_balance, 2),
            "initial_bankroll":  _PAPER_INITIAL,
            "total_return_pct":  _return_pct(paper_balance, _PAPER_INITIAL),
        },
        "live": {
            **live_stats,
            "current_bankroll_aud": round(live_balance, 2) if live_balance is not None else None,
        },
        "odds_slippage": slippage_summary,
        "bankroll_curves": {
            "paper": _curve("paper"),
            "live":  _curve("live"),
        },
        "recent_live_bets": [
            {
                "id":               o.id,
                "match_id":         o.match_id,
                "side":             o.bet_side,
                "stake_aud":        o.stake_amount_aud,
                "actual_odds":      o.actual_tab_odds,
                "recommended_odds": o.recommended_odds,
                "slippage":         o.odds_slippage,
                "won":              o.won,
                "profit_aud":       o.profit_loss_dollars,
                "placed_at":        o.placed_at.isoformat() if o.placed_at else None,
                "settled_at":       o.settled_at.isoformat() if o.settled_at else None,
            }
            for o in recent
        ],
    }


# ---------------------------------------------------------------------------
# GET /api/tab/today
# ---------------------------------------------------------------------------

@router.get("/today", summary="Today's picks — check before going to TAB")
def get_today(days_ahead: int = 3, *, db: DbSession) -> dict[str, Any]:
    """
    Compact betting brief for upcoming matches with model recommendations.

    Designed for a quick phone check before heading to the TAB counter:
      - Upcoming matches in the next `days_ahead` days with active recommendations
      - Suggested AUD stake based on live bankroll (falls back to paper if no live bets yet)
      - Current bankroll status (paper + live)
      - Minutes until next match

    Args:
        days_ahead: Look-ahead window in days (1–14). Default 3.
    """
    days_ahead = max(1, min(days_ahead, 14))
    now = datetime.now(tz=UTC)
    horizon = now + timedelta(days=days_ahead)

    # Upcoming matches with pending recommendations
    upcoming_matches = (
        db.query(Match)
        .filter(
            Match.match_time >= now,
            Match.match_time <= horizon,
            Match.result.is_(None),
        )
        .order_by(Match.match_time.asc())
        .all()
    )

    # Live / paper bankrolls for stake sizing
    live_balance = _latest_balance(db, "live")
    paper_balance = _latest_balance(db, "paper") or _PAPER_INITIAL
    stake_bankroll = live_balance if live_balance is not None else paper_balance
    using_live = live_balance is not None

    picks = []
    for match in upcoming_matches:
        # Latest prediction for this match
        pred: Prediction | None = (
            db.query(Prediction)
            .filter(Prediction.match_id == match.id)
            .order_by(Prediction.id.desc())
            .first()
        )
        if pred is None:
            continue

        rec: Recommendation | None = (
            db.query(Recommendation)
            .filter(
                Recommendation.prediction_id == pred.id,
                Recommendation.status == "pending",
            )
            .first()
        )

        # Team names
        home_team = db.get(Team, match.home_team_id)
        away_team = db.get(Team, match.away_team_id)
        home_name = home_team.short_name if home_team else str(match.home_team_id)
        away_name = away_team.short_name if away_team else str(match.away_team_id)

        # Match time for display
        mt = match.match_time
        if mt and mt.tzinfo is None:
            mt = mt.replace(tzinfo=UTC)
        minutes_until = int((mt - now).total_seconds() / 60) if mt else None

        pick: dict[str, Any] = {
            "match_id":      match.id,
            "home_team":     home_name,
            "away_team":     away_name,
            "venue":         match.venue,
            "match_time":    mt.isoformat() if mt else None,
            "minutes_until": minutes_until,
            "round":         match.round_label or f"Round {match.round_number}",
            "is_final":      match.is_final,
            "model_probs": {
                "home": round(pred.home_win_prob, 4),
                "away": round(pred.away_win_prob, 4),
            },
        }

        if rec is not None:
            # Determine edge and Kelly details
            if rec.side == "home":
                edge = pred.home_edge
            else:
                edge = pred.away_edge

            suggested_aud = (
                round(rec.stake_fraction * stake_bankroll, 2)
                if rec.stake_fraction and stake_bankroll
                else None
            )

            pick["recommendation"] = {
                "side":           rec.side,
                "recommended_odds": round(rec.recommended_odds, 3),
                "edge":           round(edge, 4) if edge is not None else None,
                "kelly_fraction": round(rec.stake_fraction, 4),
                "suggested_stake_aud": suggested_aud,
                "using_live_bankroll": using_live,
                "rec_id":         rec.id,
                # `tier` and `data_quality_ok` are not columns on Recommendation
                # and never have been — reading them raised AttributeError on
                # every call to this endpoint. Found by mypy; the path had no
                # test coverage. Reported as null until the fields either exist
                # or the response contract drops them.
                "tier":           None,
                "data_quality_ok": None,
            }
        else:
            pick["recommendation"] = None

        picks.append(pick)

    # Next match countdown
    next_match_mins: int | None = None
    if picks:
        first_mins = picks[0].get("minutes_until")
        if first_mins is not None:
            next_match_mins = first_mins

    return {
        "generated_at": now.isoformat(),
        "days_ahead":   days_ahead,
        "n_matches":    len(picks),
        "picks":        picks,
        "bankroll": {
            "paper": {
                "balance": round(paper_balance, 2),
                "initial": _PAPER_INITIAL,
                "return_pct": _return_pct(paper_balance, _PAPER_INITIAL),
            },
            "live": {
                "balance_aud": round(live_balance, 2) if live_balance is not None else None,
                "note": (
                    "Live bankroll active" if live_balance is not None
                    else "No live bets recorded yet"
                ),
            },
        },
        "next_match_minutes": next_match_mins,
    }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _latest_balance(db: Session, log_type: str) -> float | None:
    """Return the most recent balance for the given log_type, or None if no entries."""
    row = (
        db.query(BankrollLog)
        .filter(BankrollLog.log_type == log_type)
        .order_by(BankrollLog.created_at.desc())
        .first()
    )
    return float(row.balance_after) if row else None


def _compute_outcome_stats(outcomes: list[BetOutcome], use_units: bool) -> dict[str, Any]:
    """
    Compute win rate, ROI, and profit from a list of settled BetOutcome rows.

    Args:
        outcomes:   Settled BetOutcome rows.
        use_units:  True → use profit_loss_units (paper); False → use profit_loss_dollars (live).
    """
    if not outcomes:
        return {
            "n_bets":       0,
            "n_wins":       0,
            "hit_rate":     None,
            "total_profit": None,
            "roi":          None,
        }

    n = len(outcomes)
    wins = sum(1 for o in outcomes if o.won)
    hit_rate = round(wins / n, 4) if n > 0 else None

    if use_units:
        pl_vals = [o.profit_loss_units for o in outcomes if o.profit_loss_units is not None]
        stake_vals = [o.stake_fraction for o in outcomes if o.stake_fraction is not None]
    else:
        pl_vals = [o.profit_loss_dollars for o in outcomes if o.profit_loss_dollars is not None]
        stake_vals = [o.stake_amount_aud for o in outcomes if o.stake_amount_aud is not None]

    total_profit = round(sum(pl_vals), 4) if pl_vals else None
    total_staked = sum(stake_vals) if stake_vals else 0.0
    roi = round(sum(pl_vals) / total_staked, 4) if (pl_vals and total_staked > 0) else None

    label = "units" if use_units else "aud"
    return {
        "n_bets":                   n,
        "n_wins":                   wins,
        "hit_rate":                 hit_rate,
        f"total_profit_{label}":    total_profit,
        f"total_staked_{label}":    round(total_staked, 4) if total_staked else None,
        "roi":                      roi,
    }


def _return_pct(current: float, initial: float) -> float | None:
    if initial and initial > 0:
        return round((current - initial) / initial * 100, 2)
    return None
