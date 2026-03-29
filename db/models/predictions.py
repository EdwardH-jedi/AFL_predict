"""db/models/predictions.py — Per-match model predictions."""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base


class Prediction(Base):
    __tablename__ = "predictions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[int] = mapped_column(Integer, ForeignKey("matches.id"), nullable=False, index=True)
    model_run_id: Mapped[int] = mapped_column(Integer, ForeignKey("model_runs.id"), nullable=False, index=True)

    # Model's predicted win probability for the home team
    home_win_prob: Mapped[float] = mapped_column(Float, nullable=False)
    away_win_prob: Mapped[float] = mapped_column(Float, nullable=False)

    # Edge over bookmaker implied probability (can be negative)
    home_edge: Mapped[float | None] = mapped_column(Float, nullable=True)
    away_edge: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Recommended Kelly fraction (conservative, capped by settings.max_kelly_fraction)
    kelly_home: Mapped[float | None] = mapped_column(Float, nullable=True)
    kelly_away: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    match: Mapped["Match"] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "Match", back_populates="predictions"
    )
    model_run: Mapped["ModelRun"] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "ModelRun", back_populates="predictions"
    )
    recommendation: Mapped["Recommendation | None"] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "Recommendation", back_populates="prediction", uselist=False
    )

    def __repr__(self) -> str:
        return (
            f"<Prediction match_id={self.match_id} home_prob={self.home_win_prob:.3f} "
            f"away_prob={self.away_win_prob:.3f}>"
        )
