"""db/models/match_features.py — Pre-match feature vector for each AFL game."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, SmallInteger, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base


class MatchFeature(Base):
    """
    Stores the pre-match feature vector for a single match.

    One row per match. All values must represent state knowable strictly
    before match_time (no future leakage).

    ELO, form, and bookmaker features are written by the build_features job
    after fixtures and odds have been ingested.
    """

    __tablename__ = "match_features"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("matches.id"), nullable=False, unique=True, index=True
    )

    # --- Denormalised identifiers (avoid joins in model training) ---
    season: Mapped[int] = mapped_column(SmallInteger, nullable=False, index=True)
    round_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    home_team_id: Mapped[int] = mapped_column(Integer, nullable=False)
    away_team_id: Mapped[int] = mapped_column(Integer, nullable=False)
    match_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_final: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # --- ELO ratings (pre-match snapshot, before home advantage is applied) ---
    home_elo_pre: Mapped[float | None] = mapped_column(Float, nullable=True)
    away_elo_pre: Mapped[float | None] = mapped_column(Float, nullable=True)
    elo_diff: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- Rolling form — home team (last 10 games before this match) ---
    home_win_rate_l10: Mapped[float | None] = mapped_column(Float, nullable=True)
    home_avg_pts_for_l10: Mapped[float | None] = mapped_column(Float, nullable=True)
    home_avg_pts_against_l10: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- Rolling form — away team ---
    away_win_rate_l10: Mapped[float | None] = mapped_column(Float, nullable=True)
    away_avg_pts_for_l10: Mapped[float | None] = mapped_column(Float, nullable=True)
    away_avg_pts_against_l10: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- Bookmaker features (latest pre-match odds snapshot) ---
    bm_home_odds: Mapped[float | None] = mapped_column(Float, nullable=True)
    bm_away_odds: Mapped[float | None] = mapped_column(Float, nullable=True)
    bm_home_implied_prob: Mapped[float | None] = mapped_column(Float, nullable=True)
    bm_away_implied_prob: Mapped[float | None] = mapped_column(Float, nullable=True)
    bm_overround: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- Rest / travel ---
    home_rest_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    away_rest_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # --- Venue ---
    venue: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # --- Target variable (None before match is played) ---
    # 1 = home win, 0 = away win, None = not yet played or draw
    home_win: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # --- Metadata ---
    feature_computed_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    match: Mapped["Match"] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "Match", back_populates="features"
    )

    def __repr__(self) -> str:
        return (
            f"<MatchFeature match_id={self.match_id} "
            f"S{self.season}R{self.round_number}>"
        )
