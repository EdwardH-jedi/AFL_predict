"""db/models/matches.py — AFL fixture and result data."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, SmallInteger, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base


class Match(Base):
    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Season / round context
    season: Mapped[int] = mapped_column(SmallInteger, nullable=False, index=True)
    round_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    # e.g. "Round 5", "Finals Week 1"
    round_label: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Teams
    home_team_id: Mapped[int] = mapped_column(Integer, ForeignKey("teams.id"), nullable=False)
    away_team_id: Mapped[int] = mapped_column(Integer, ForeignKey("teams.id"), nullable=False)

    # Scheduling
    match_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    venue: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Result (null until settled)
    home_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    away_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 'home' | 'away' | 'draw' | None
    result: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # Finals flag — informs model features and evaluation
    is_final: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # True when the API-designated home team is NOT at their registered home ground
    # (Gather Round, neutral interstate venues, MCG finals for non-Melbourne teams).
    # ELO home advantage should be zeroed for these matches.
    is_neutral_venue: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # External reference ID from data source (for deduplication)
    external_id: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    home_team: Mapped["Team"] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "Team", foreign_keys=[home_team_id], back_populates="home_matches"
    )
    away_team: Mapped["Team"] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "Team", foreign_keys=[away_team_id], back_populates="away_matches"
    )
    odds_snapshots: Mapped[list["OddsSnapshot"]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "OddsSnapshot", back_populates="match"
    )
    predictions: Mapped[list["Prediction"]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "Prediction", back_populates="match"
    )
    features: Mapped["MatchFeature | None"] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "MatchFeature", back_populates="match", uselist=False
    )

    def __repr__(self) -> str:
        return f"<Match id={self.id} season={self.season} round={self.round_number}>"
