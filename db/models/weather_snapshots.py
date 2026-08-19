"""db/models/weather_snapshots.py - Pre-match weather conditions per match."""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base


class WeatherSnapshot(Base):
    """
    Weather conditions for one match, fetched from Open-Meteo API.

    Populated by WeatherCollector using the match venue's coordinates.
    One row per match.

    AFL weather is crucial for score prediction:
      - High wind reduces accuracy / scoring
      - Rain increases contested ball, reduces scoring
      - Extreme heat (>35C) affects late-game fitness

    Source: Open-Meteo (open-meteo.com) - free, no API key required.
    Forecast API for upcoming matches; Archive API for historical matches.
    """

    __tablename__ = "weather_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("matches.id"), unique=True, nullable=False, index=True
    )

    # Venue coordinates used for the weather query
    venue_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- Conditions at match kickoff time ---
    temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    apparent_temp_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    precipitation_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind_speed_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind_gusts_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind_direction_deg: Mapped[float | None] = mapped_column(Float, nullable=True)
    cloud_cover_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    # WMO weather code (0=clear, 61-67=rain, 71-77=snow, etc.)
    weather_code: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Derived: is it raining? (precipitation > 0.5mm or weather_code in rain range)
    is_raining: Mapped[bool | None] = mapped_column(
        Integer, nullable=True
    )  # stored as int for SQLite
    # High wind flag: wind_speed > 40 km/h significantly affects AFL scoring
    is_high_wind: Mapped[bool | None] = mapped_column(Integer, nullable=True)
    # Extreme heat flag: >35C
    is_extreme_heat: Mapped[bool | None] = mapped_column(Integer, nullable=True)

    # 'forecast' (upcoming match) or 'archive' (historical)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False, default="forecast")
    fetched_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationship
    match: Mapped["Match"] = relationship("Match")  # type: ignore[name-defined]  # noqa: F821

    def __repr__(self) -> str:
        return (
            f"<WeatherSnapshot match_id={self.match_id} "
            f"temp={self.temperature_c}C wind={self.wind_speed_kmh}kmh "
            f"rain={self.is_raining}>"
        )
