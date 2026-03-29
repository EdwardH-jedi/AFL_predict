"""db/models/bet_outcomes.py — Settled result for each recommendation."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base


class BetOutcome(Base):
    __tablename__ = "bet_outcomes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recommendation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("recommendations.id"), unique=True, nullable=False, index=True
    )

    # Did the recommended side win?
    won: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # Profit/loss in stake units (e.g. 1.85 - 1 = 0.85 if won, -1 if lost)
    profit_loss_units: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Profit/loss in dollars (null if stake_dollars was null)
    profit_loss_dollars: Mapped[float | None] = mapped_column(Float, nullable=True)

    settled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    recommendation: Mapped["Recommendation"] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "Recommendation", back_populates="bet_outcome"
    )

    def __repr__(self) -> str:
        return (
            f"<BetOutcome recommendation_id={self.recommendation_id} won={self.won} "
            f"pl_units={self.profit_loss_units}>"
        )
