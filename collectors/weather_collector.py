"""
collectors/weather_collector.py
---------------------------------
Weather data collector using Open-Meteo API (open-meteo.com).

Open-Meteo is completely free, requires no API key, and provides:
  - Forecast API: upcoming 7-16 days weather at any coordinates
  - Archive API: historical weather back to 1940

AFL venues are mapped to GPS coordinates so we can fetch weather
at the exact match location.

Usage:
    collector = WeatherCollector(db)
    collector.fetch_upcoming()          # fetch weather for next 7 days of matches
    collector.fetch_historical(season)  # backfill historical season

API endpoints:
    Forecast: https://api.open-meteo.com/v1/forecast
    Archive:  https://archive-api.open-meteo.com/v1/archive

Parameters fetched (hourly, at match kickoff hour):
    temperature_2m, apparent_temperature, precipitation,
    windspeed_10m, windgusts_10m, winddirection_10m,
    cloudcover, weathercode
"""

from __future__ import annotations

import time
from datetime import UTC, date, datetime

import httpx
from loguru import logger
from sqlalchemy.orm import Session

from db.models.matches import Match
from db.models.weather_snapshots import WeatherSnapshot

_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
_REQUEST_DELAY = 0.5  # seconds between API calls (Open-Meteo asks for polite use)

# Wind threshold for AFL impact (km/h)
_HIGH_WIND_KMH = 40.0
# Rain threshold (mm/h)
_RAIN_MM = 0.5
# Extreme heat (C)
_EXTREME_HEAT_C = 35.0

# WMO weather codes for rain/showers (61-67, 80-82)
_RAIN_CODES = frozenset(range(61, 68)) | frozenset(range(80, 83)) | frozenset(range(95, 100))

# ---------------------------------------------------------------------------
# AFL venue GPS coordinates
# Source: Google Maps / official AFL venue data
# ---------------------------------------------------------------------------

VENUE_COORDS: dict[str, tuple[float, float]] = {
    # MCG - Melbourne Cricket Ground
    "MCG": (-37.8200, 144.9834),
    "Melbourne Cricket Ground": (-37.8200, 144.9834),
    # Marvel Stadium
    "Marvel Stadium": (-37.8167, 144.9475),
    "Etihad Stadium": (-37.8167, 144.9475),
    "Docklands": (-37.8167, 144.9475),
    # GMHBA Stadium (Geelong)
    "GMHBA Stadium": (-38.1560, 144.3552),
    "Kardinia Park": (-38.1560, 144.3552),
    # Adelaide Oval
    "Adelaide Oval": (-34.9158, 138.5961),
    # Optus Stadium (Perth)
    "Optus Stadium": (-31.9514, 115.8875),
    "Perth Stadium": (-31.9514, 115.8875),
    # Gabba (Brisbane)
    "Gabba": (-27.4858, 153.0381),
    "The Gabba": (-27.4858, 153.0381),
    "Brisbane Cricket Ground": (-27.4858, 153.0381),
    # Sydney Cricket Ground
    "Sydney Cricket Ground": (-33.8912, 151.2247),
    "SCG": (-33.8912, 151.2247),
    # Giants Stadium / Engie Stadium (GWS)
    "Engie Stadium": (-33.8688, 150.9347),
    "Giants Stadium": (-33.8688, 150.9347),
    "GIANTS Stadium": (-33.8688, 150.9347),
    # TIO Traeger Park (Alice Springs)
    "TIO Traeger Park": (-23.6980, 133.8807),
    "Traeger Park": (-23.6980, 133.8807),
    # Riverway Stadium (Townsville)
    "Riverway Stadium": (-19.3197, 146.7544),
    # UTAS Stadium (Launceston)
    "UTAS Stadium": (-41.4549, 147.1426),
    "York Park": (-41.4549, 147.1426),
    # Blundstone Arena (Hobart)
    "Blundstone Arena": (-42.8794, 147.3294),
    "Bellerive Oval": (-42.8794, 147.3294),
    # TIO Stadium (Darwin)
    "TIO Stadium": (-12.4065, 130.8675),
    # Cazalys Stadium (Cairns)
    "Cazalys Stadium": (-16.9252, 145.7679),
    # Norwood Oval
    "Norwood Oval": (-34.9239, 138.6368),
    # Manuka Oval (Canberra)
    "Manuka Oval": (-35.3193, 149.1326),
    # Jiangwan Stadium (Shanghai)
    "Jiangwan Stadium": (31.3335, 121.5193),
}

# Default fallback: Melbourne (most AFL games)
_DEFAULT_COORDS = (-37.8136, 144.9631)


def get_venue_coords(venue: str | None) -> tuple[float, float]:
    """Return (lat, lon) for a venue string, with fuzzy matching and Melbourne fallback."""
    if not venue:
        return _DEFAULT_COORDS
    # Exact match
    if venue in VENUE_COORDS:
        return VENUE_COORDS[venue]
    # Partial match (case-insensitive)
    venue_lower = venue.lower()
    for key, coords in VENUE_COORDS.items():
        if key.lower() in venue_lower or venue_lower in key.lower():
            return coords
    logger.debug(f"WeatherCollector: unknown venue {venue!r} - using Melbourne coords.")
    return _DEFAULT_COORDS


class WeatherCollector:
    """
    Fetches and stores weather snapshots for AFL matches via Open-Meteo.

    Requires a SQLAlchemy Session to read matches and write weather snapshots.
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    def fetch_upcoming(self, days_ahead: int = 14) -> int:
        """
        Fetch weather for all upcoming matches in the next N days.

        Args:
            days_ahead: How many days of upcoming matches to fetch weather for.

        Returns:
            Number of weather snapshots created/updated.
        """
        today = date.today()
        cutoff = datetime(today.year, today.month, today.day, tzinfo=UTC)
        from datetime import timedelta
        end_cutoff = cutoff + timedelta(days=days_ahead)

        matches = (
            self._db.query(Match)
            .filter(Match.match_time >= cutoff)
            .filter(Match.match_time <= end_cutoff)
            .order_by(Match.match_time.asc())
            .all()
        )

        count = 0
        for match in matches:
            if self._fetch_and_store(match, source_type="forecast"):
                count += 1
            time.sleep(_REQUEST_DELAY)

        logger.info(
            f"WeatherCollector: fetched forecast for {count}/{len(matches)} upcoming matches."
        )
        return count

    def fetch_historical(self, season: int) -> int:
        """
        Backfill historical weather for all matches in a season.

        Args:
            season: AFL season year.

        Returns:
            Number of weather snapshots created/updated.
        """
        matches = (
            self._db.query(Match)
            .filter(Match.season == season)
            .filter(Match.match_time.isnot(None))
            .order_by(Match.match_time.asc())
            .all()
        )

        count = 0
        for match in matches:
            # Skip if already have weather data
            existing = (
                self._db.query(WeatherSnapshot)
                .filter(WeatherSnapshot.match_id == match.id)
                .first()
            )
            if existing and existing.temperature_c is not None:
                continue

            if self._fetch_and_store(match, source_type="archive"):
                count += 1
            time.sleep(_REQUEST_DELAY)

        logger.info(
            f"WeatherCollector: backfilled {count}/{len(matches)} "
            f"historical weather records for {season}."
        )
        return count

    # ---------------------------------------------------------------------------
    # Internal
    # ---------------------------------------------------------------------------

    def _fetch_and_store(self, match: Match, source_type: str) -> bool:
        """Fetch weather for one match and upsert into DB. Returns True on success."""
        if match.match_time is None:
            return False

        lat, lon = get_venue_coords(match.venue)
        match_dt = match.match_time
        if match_dt.tzinfo is None:
            match_dt = match_dt.replace(tzinfo=UTC)

        date_str = match_dt.strftime("%Y-%m-%d")

        params = {
            "latitude": lat,
            "longitude": lon,
            "hourly": ",".join([
                "temperature_2m",
                "apparent_temperature",
                "precipitation",
                "windspeed_10m",
                "windgusts_10m",
                "winddirection_10m",
                "cloudcover",
                "weathercode",
            ]),
            "timezone": "Australia/Melbourne",
            "start_date": date_str,
            "end_date": date_str,
        }

        if source_type == "archive":
            url = _ARCHIVE_URL
        else:
            url = _FORECAST_URL

        try:
            resp = httpx.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning(f"WeatherCollector: failed for match {match.id} ({match.venue}): {e}")
            return False

        weather = self._extract_hour(data, match_dt)
        if weather is None:
            return False

        # Derive flags
        rain = bool(
            (weather.get("precipitation") or 0) > _RAIN_MM
            or int(weather.get("weathercode") or 0) in _RAIN_CODES
        )
        wind = bool((weather.get("windspeed_10m") or 0) > _HIGH_WIND_KMH)
        heat = bool((weather.get("temperature_2m") or 0) > _EXTREME_HEAT_C)

        existing = (
            self._db.query(WeatherSnapshot)
            .filter(WeatherSnapshot.match_id == match.id)
            .first()
        )

        if existing:
            snap = existing
        else:
            snap = WeatherSnapshot(match_id=match.id)
            self._db.add(snap)

        snap.venue_name = match.venue
        snap.latitude = lat
        snap.longitude = lon
        snap.temperature_c = weather.get("temperature_2m")
        snap.apparent_temp_c = weather.get("apparent_temperature")
        snap.precipitation_mm = weather.get("precipitation")
        snap.wind_speed_kmh = weather.get("windspeed_10m")
        snap.wind_gusts_kmh = weather.get("windgusts_10m")
        snap.wind_direction_deg = weather.get("winddirection_10m")
        snap.cloud_cover_pct = weather.get("cloudcover")
        snap.weather_code = weather.get("weathercode")
        snap.is_raining = int(rain)
        snap.is_high_wind = int(wind)
        snap.is_extreme_heat = int(heat)
        snap.source_type = source_type

        try:
            self._db.commit()
        except Exception as exc:
            # UNIQUE constraint (duplicate) — another run already inserted this row.
            # Roll back the failed transaction and continue gracefully.
            self._db.rollback()
            logger.debug(
                f"WeatherCollector: skipping match {match.id} after commit error "
                f"(probably duplicate): {exc}"
            )
            return False
        return True

    @staticmethod
    def _extract_hour(data: dict, target_dt: datetime) -> dict | None:
        """
        Extract hourly weather values for the hour closest to match kickoff.
        """
        try:
            hourly = data.get("hourly", {})
            times = hourly.get("time", [])
            if not times:
                return None

            target_hour = target_dt.strftime("%Y-%m-%dT%H:00")
            # Find exact match or nearest hour
            idx = None
            for i, t in enumerate(times):
                if t == target_hour:
                    idx = i
                    break
            if idx is None:
                # Fallback: use the middle of the day (noon)
                noon = target_dt.strftime("%Y-%m-%dT12:00")
                for i, t in enumerate(times):
                    if t == noon:
                        idx = i
                        break
            if idx is None:
                idx = len(times) // 2  # absolute fallback

            return {
                col: vals[idx]
                for col, vals in hourly.items()
                if col != "time" and isinstance(vals, list) and idx < len(vals)
            }
        except Exception:
            return None
