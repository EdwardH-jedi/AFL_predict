"""
evaluation/clv_tracker.py
--------------------------
Closing Line Value (CLV) tracker.

CLV is the single most reliable long-term predictor of betting profitability.
It measures whether the odds we bet at were *better than the market's final
assessment* before the game started.

How it works:
  - bet_prob     = 1 / recommended_odds  (implied probability at bet time)
  - closing_prob = 1 / closing_odds      (implied probability at last pre-match snapshot)
  - clv          = closing_prob - bet_prob
                   Positive → we beat the closing line (good: market moved toward us)
                   Negative → market moved away from us (warning sign)
  - clv_pct      = clv / closing_prob * 100  (CLV as % of closing probability)

Why CLV matters more than short-term ROI:
  - ROI on small AFL samples is noisy (±3% ROI can easily be luck).
  - Consistently positive CLV across many bets is strong evidence of genuine edge.
  - A model that beats the closing line by +2% on average will be profitable long-term.

Reference: Joseph Buchdahl, "Squares & Sharps, Suckers & Sharks" (2016).

Public API:
    compute_clv(rec, closing_snapshot) → CLVRecord
    batch_clv(session, recommendation_ids) → list[CLVRecord]
    clv_summary(records) → dict
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from loguru import logger
from sqlalchemy.orm import Session

from db.models.odds_snapshots import OddsSnapshot
from db.models.predictions import Prediction
from db.models.recommendations import Recommendation

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class CLVRecord:
    """CLV calculation result for one bet."""
    recommendation_id: int
    match_id: int
    side: str                     # 'home' | 'away'
    recommended_odds: float       # odds at bet time
    closing_odds: float | None    # last pre-match odds (None if not available)
    bet_prob: float               # 1 / recommended_odds
    closing_prob: float | None    # 1 / closing_odds
    clv: float | None             # closing_prob - bet_prob (positive = beat the line)
    clv_pct: float | None         # clv / closing_prob * 100
    closing_snapshot_time: datetime | None = None

    @property
    def beat_closing_line(self) -> bool | None:
        """True if CLV > 0 (we got better odds than the market settled at)."""
        if self.clv is None:
            return None
        return self.clv > 0


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute_clv(
    recommendation: Recommendation,
    closing_snapshot: OddsSnapshot | None,
) -> CLVRecord:
    """
    Compute CLV for a single recommendation.

    Args:
        recommendation: A Recommendation ORM object (must have .prediction loaded).
        closing_snapshot: The last OddsSnapshot before match_time (may be None).

    Returns:
        CLVRecord with all fields populated.
    """
    side = recommendation.side
    rec_odds = recommendation.recommended_odds
    bet_prob = 1.0 / rec_odds if rec_odds and rec_odds > 1 else None

    if closing_snapshot is None or bet_prob is None:
        return CLVRecord(
            recommendation_id=recommendation.id,
            match_id=recommendation.prediction.match_id,
            side=side,
            recommended_odds=rec_odds,
            closing_odds=None,
            bet_prob=bet_prob or math.nan,
            closing_prob=None,
            clv=None,
            clv_pct=None,
        )

    # Pick odds for the correct side from the closing snapshot
    if side == "home":
        closing_odds = closing_snapshot.home_odds
    else:
        closing_odds = closing_snapshot.away_odds

    if closing_odds is None or closing_odds <= 1:
        return CLVRecord(
            recommendation_id=recommendation.id,
            match_id=recommendation.prediction.match_id,
            side=side,
            recommended_odds=rec_odds,
            closing_odds=closing_odds,
            bet_prob=round(bet_prob, 6),
            closing_prob=None,
            clv=None,
            clv_pct=None,
            closing_snapshot_time=closing_snapshot.snapshot_time,
        )

    closing_prob = 1.0 / closing_odds
    clv = closing_prob - bet_prob
    clv_pct = (clv / closing_prob * 100) if closing_prob > 0 else None

    return CLVRecord(
        recommendation_id=recommendation.id,
        match_id=recommendation.prediction.match_id,
        side=side,
        recommended_odds=rec_odds,
        closing_odds=round(closing_odds, 4),
        bet_prob=round(bet_prob, 6),
        closing_prob=round(closing_prob, 6),
        clv=round(clv, 6),
        clv_pct=round(clv_pct, 4) if clv_pct is not None else None,
        closing_snapshot_time=closing_snapshot.snapshot_time,
    )


# ---------------------------------------------------------------------------
# Batch computation
# ---------------------------------------------------------------------------

def batch_clv(
    session: Session,
    recommendation_ids: Sequence[int] | None = None,
) -> list[CLVRecord]:
    """
    Compute CLV for multiple recommendations.

    Args:
        session: SQLAlchemy session.
        recommendation_ids: IDs to process. If None, processes all settled recs.

    Returns:
        List of CLVRecord, one per recommendation that has odds data.
    """
    query = (
        session.query(Recommendation)
        .join(Prediction, Recommendation.prediction_id == Prediction.id)
    )
    if recommendation_ids is not None:
        query = query.filter(Recommendation.id.in_(recommendation_ids))
    else:
        query = query.filter(Recommendation.status == "settled")

    recommendations = query.all()
    records: list[CLVRecord] = []

    for rec in recommendations:
        pred: Prediction = rec.prediction
        match_id = pred.match_id

        # Closing odds = latest pre-match snapshot
        closing: OddsSnapshot | None = (
            session.query(OddsSnapshot)
            .filter(OddsSnapshot.match_id == match_id)
            .filter(OddsSnapshot.snapshot_time < pred.match.match_time)  # type: ignore[union-attr]
            .order_by(OddsSnapshot.snapshot_time.desc())
            .first()
        )

        records.append(compute_clv(rec, closing))

    logger.info(
        f"CLV: computed {len(records)} records, "
        f"{sum(1 for r in records if r.clv is not None)} with closing odds available."
    )
    return records


# ---------------------------------------------------------------------------
# Aggregate summary
# ---------------------------------------------------------------------------

def clv_summary(records: list[CLVRecord]) -> dict:
    """
    Aggregate CLV statistics across a list of CLVRecords.

    Returns a dict suitable for dashboard display or JSON serialisation.
    Key metrics:
      - n_bets            : total bets evaluated
      - n_with_clv        : bets where closing odds were available
      - beat_closing_line : fraction with CLV > 0 (higher = more consistent edge)
      - avg_clv           : mean CLV (positive = beating the market on average)
      - avg_clv_pct       : mean CLV as % of closing probability
      - median_clv_pct    : median CLV% (robust to outliers)
    """
    n_total = len(records)
    clv_records = [r for r in records if r.clv is not None]
    n_with_clv = len(clv_records)

    if not clv_records:
        return {
            "n_bets": n_total,
            "n_with_clv": 0,
            "beat_closing_line": None,
            "avg_clv": None,
            "avg_clv_pct": None,
            "median_clv_pct": None,
        }

    clv_vals = [r.clv for r in clv_records]  # type: ignore[misc]
    clv_pct_vals = [r.clv_pct for r in clv_records if r.clv_pct is not None]

    beat = sum(1 for v in clv_vals if v > 0)
    avg_clv = sum(clv_vals) / len(clv_vals)
    avg_clv_pct = sum(clv_pct_vals) / len(clv_pct_vals) if clv_pct_vals else None

    sorted_pct = sorted(clv_pct_vals)
    n = len(sorted_pct)
    median_clv_pct = (
        sorted_pct[n // 2] if n % 2 == 1
        else (sorted_pct[n // 2 - 1] + sorted_pct[n // 2]) / 2
    ) if sorted_pct else None

    return {
        "n_bets": n_total,
        "n_with_clv": n_with_clv,
        "beat_closing_line": round(beat / n_with_clv, 4),
        "avg_clv": round(avg_clv, 6),
        "avg_clv_pct": round(avg_clv_pct, 4) if avg_clv_pct is not None else None,
        "median_clv_pct": round(median_clv_pct, 4) if median_clv_pct is not None else None,
    }
