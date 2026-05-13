"""db/models/bet_outcomes.py — Settled result for each recommendation or live TAB bet."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base


class BetOutcome(Base):
    __tablename__ = "bet_outcomes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # FK to the paper-trade recommendation this outcome belongs to.
    # NULL for manually recorded TAB live bets with no matching recommendation.
    recommendation_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("recommendations.id"), unique=True, nullable=True, index=True
    )

    # Direct match reference — populated for tab_live bets.
    match_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    # Which side was backed ('home' | 'away')
    bet_side: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # 'paper' — model-generated paper-trade outcome (default)
    # 'tab_live' — manually recorded TAB shop bet
    bet_source: Mapped[str] = mapped_column(
        String(20), nullable=False, default="paper", server_default="paper"
    )

    # Odds at time of recommendation (for slippage calc)
    recommended_odds: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Actual decimal odds received at the TAB counter
    actual_tab_odds: Mapped[float | None] = mapped_column(Float, nullable=True)

    # actual_tab_odds - recommended_odds (negative = worse than expected)
    odds_slippage: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Kelly fraction stake (mirrors Recommendation.stake_fraction for paper trades)
    stake_fraction: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Actual AUD stake placed at TAB
    stake_amount_aud: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Did the recommended / placed side win?
    won: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # Profit/loss in Kelly-fraction units
    profit_loss_units: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Profit/loss in AUD
    profit_loss_dollars: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Total payout received from TAB (stake + winnings; 0 on loss)
    payout_amount_aud: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Closing Line Value (populated by settle_results at settlement time)
    closing_odds: Mapped[float | None] = mapped_column(Float, nullable=True)
    closing_implied_prob: Mapped[float | None] = mapped_column(Float, nullable=True)
    clv: Mapped[float | None] = mapped_column(Float, nullable=True)
    clv_computed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    placed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    recommendation: Mapped["Recommendation | None"] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "Recommendation", back_populates="bet_outcome"
    )

    def __repr__(self) -> str:
        return (
            f"<BetOutcome id={self.id} source={self.bet_source!r} "
            f"match_id={self.match_id} won={self.won} pl_units={self.profit_loss_units}>"
        )
