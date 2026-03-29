"""db/models/recommendations.py — Actionable betting recommendations (paper-trade by default)."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    prediction_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("predictions.id"), unique=True, nullable=False, index=True
    )

    # Which side to back: 'home' | 'away'
    side: Mapped[str] = mapped_column(String(10), nullable=False)

    # Odds at time of recommendation
    recommended_odds: Mapped[float] = mapped_column(Float, nullable=False)

    # Suggested stake as a fraction of bankroll (Kelly-derived, capped)
    stake_fraction: Mapped[float] = mapped_column(Float, nullable=False)

    # Absolute stake in dollars (null until bankroll is set)
    stake_dollars: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Always True in MVP — no live betting
    paper_trade: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # 'pending' | 'settled' | 'void'
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    prediction: Mapped["Prediction"] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "Prediction", back_populates="recommendation"
    )
    bet_outcome: Mapped["BetOutcome | None"] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "BetOutcome", back_populates="recommendation", uselist=False
    )

    def __repr__(self) -> str:
        return (
            f"<Recommendation id={self.id} side={self.side!r} odds={self.recommended_odds} "
            f"stake_fraction={self.stake_fraction:.4f} paper={self.paper_trade}>"
        )
