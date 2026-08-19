"""db/models/odds_snapshots.py — TAB H2H odds snapshots for a match."""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base


class OddsSnapshot(Base):
    __tablename__ = "odds_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("matches.id"), nullable=False, index=True
    )

    # Source identifier — TAB or other bookmaker
    bookmaker: Mapped[str] = mapped_column(String(50), nullable=False, default="TAB")

    # Pre-match H2H decimal odds
    home_odds: Mapped[float | None] = mapped_column(Float, nullable=True)
    away_odds: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Derived: implied probabilities (1/odds normalised for overround)
    home_implied_prob: Mapped[float | None] = mapped_column(Float, nullable=True)
    away_implied_prob: Mapped[float | None] = mapped_column(Float, nullable=True)
    overround: Mapped[float | None] = mapped_column(Float, nullable=True)

    # When this snapshot was captured
    snapshot_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)

    # 'opening' | 'closing' | 'scheduled' — type of snapshot
    snapshot_type: Mapped[str] = mapped_column(String(20), nullable=False, default="scheduled")

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    match: Mapped["Match"] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "Match", back_populates="odds_snapshots"
    )

    def __repr__(self) -> str:
        return (
            f"<OddsSnapshot match_id={self.match_id} bookmaker={self.bookmaker!r} "
            f"home={self.home_odds} away={self.away_odds}>"
        )
