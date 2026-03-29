"""db/models/teams.py — AFL team reference data."""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    short_name: Mapped[str] = mapped_column(String(10), nullable=False)
    # State/city for display purposes
    state: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # External reference ID from data source (e.g. Squiggle team ID)
    external_id: Mapped[str | None] = mapped_column(String(50), unique=True, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships (matches where this team is home or away)
    home_matches: Mapped[list["Match"]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "Match", foreign_keys="Match.home_team_id", back_populates="home_team"
    )
    away_matches: Mapped[list["Match"]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "Match", foreign_keys="Match.away_team_id", back_populates="away_team"
    )

    def __repr__(self) -> str:
        return f"<Team id={self.id} name={self.name!r}>"
