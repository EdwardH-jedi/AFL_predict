"""db/models/player_lineups.py - AFL team lineup / player availability per match."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, SmallInteger, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base


class PlayerLineup(Base):
    """
    Stores the announced team list for one team in one match.

    One row per (match_id, team_id) pair.  Populated by the player collector
    from AFL Tables historical data or AFL announcement scraping.

    Availability index:
        Ranges 0.0 - 1.0.  1.0 = full-strength lineup (no key absences).
        Computed by the collector based on missing players' historical
        contribution scores (avg disposals + goals in prior 5 games,
        normalised to team average).

    Source types:
        'afltables'  - scraped from afltables.com (historical, reliable)
        'manual'     - entered manually (for testing / backfill)
        'announcement' - scraped from AFL website team announcement page
    """

    __tablename__ = "player_lineups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[int] = mapped_column(Integer, ForeignKey("matches.id"), nullable=False, index=True)
    team_id: Mapped[int] = mapped_column(Integer, ForeignKey("teams.id"), nullable=False, index=True)

    # Number of players named in the lineup (should be 22 + 4 emergency)
    players_listed: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    players_absent: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    # Count of "key" players (top-5 by avg disposals in prior 5 games) absent
    key_players_absent: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    # Aggregate availability: 1.0 = full strength, <1.0 = weakened
    # Formula: 1 - sum(absent_player_share) where share = player_contribution / team_avg
    availability_index: Mapped[float | None] = mapped_column(Float, nullable=True)

    # When the lineup was announced (for leakage enforcement)
    announced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Data source identifier
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="afltables")

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    match: Mapped["Match"] = relationship("Match")  # type: ignore[name-defined]  # noqa: F821
    team: Mapped["Team"] = relationship("Team")  # type: ignore[name-defined]  # noqa: F821

    def __repr__(self) -> str:
        return (
            f"<PlayerLineup match_id={self.match_id} team_id={self.team_id} "
            f"avail={self.availability_index}>"
        )


class PlayerStat(Base):
    """
    Per-player per-match performance stats used to compute availability_index.

    Sourced from AFL Tables historical data.  Only the columns needed for
    contribution scoring are stored (disposals, goals, behinds, kicks, handballs).
    """

    __tablename__ = "player_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[int] = mapped_column(Integer, ForeignKey("matches.id"), nullable=False, index=True)
    team_id: Mapped[int] = mapped_column(Integer, ForeignKey("teams.id"), nullable=False, index=True)

    # Player identifier (AFL Tables player ID)
    player_external_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    player_name: Mapped[str] = mapped_column(String(100), nullable=False)

    # Core performance stats
    disposals: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    kicks: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    handballs: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    goals: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    behinds: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    # Pre-computed contribution score for this match
    # = (disposals + goals * 3) / team_avg_score in this window
    contribution_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    def __repr__(self) -> str:
        return f"<PlayerStat match_id={self.match_id} player={self.player_name!r} disp={self.disposals}>"
