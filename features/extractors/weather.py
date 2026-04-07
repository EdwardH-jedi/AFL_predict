"""
features/extractors/weather.py
--------------------------------
Weather feature extractor.

Reads pre-fetched weather snapshots from the weather_snapshots table and
converts them into model-ready features for each match.

Features produced:
  - weather_temp_c         : temperature at kickoff (Celsius)
  - weather_wind_kmh       : wind speed at kickoff (km/h)
  - weather_precip_mm      : precipitation (mm/h)
  - weather_is_raining     : 1 if precipitation > 0.5mm or rain weather code
  - weather_is_high_wind   : 1 if wind > 40 km/h
  - weather_is_extreme_heat: 1 if temperature > 35C
  - weather_scoring_index  : composite score of expected scoring impact
                             (1.0 = neutral, <1.0 = conditions reduce scoring)

weather_scoring_index formula:
  Derived from published AFL research on weather effects:
    - Each 10 km/h of wind above 20 km/h reduces scoring ~3%
    - Rain reduces scoring ~5%
    - Extreme heat (>35C) reduces scoring ~2% (late game fatigue)
  Index = 1.0 - wind_penalty - rain_penalty - heat_penalty
  Capped to [0.5, 1.0].

Leakage policy:
  Weather is fetched for the match kickoff time (not after). Historical
  weather data from Open-Meteo is an observation, not a prediction.
  No leakage risk: we're using actual conditions at the time of play.
  For upcoming matches, forecast weather is used — clearly available pre-match.

Requires a SQLAlchemy Session.
"""

from __future__ import annotations

from loguru import logger
from sqlalchemy.orm import Session

from db.models.matches import Match
from db.models.weather_snapshots import WeatherSnapshot
from features.extractors.base import BaseExtractor

_WIND_THRESHOLD_KMH = 20.0   # wind above this starts affecting scoring
_WIND_PENALTY_PER_10KMH = 0.03
_RAIN_PENALTY = 0.05
_HEAT_PENALTY = 0.02
_INDEX_MIN = 0.5

_NULL_FEATURES: dict = {
    "weather_temp_c": None,
    "weather_wind_kmh": None,
    "weather_precip_mm": None,
    "weather_is_raining": 0,
    "weather_is_high_wind": 0,
    "weather_is_extreme_heat": 0,
    "weather_scoring_index": 1.0,  # neutral default
}


class WeatherExtractor(BaseExtractor):
    """
    Extracts weather features from pre-fetched WeatherSnapshot records.

    Gracefully returns neutral defaults when weather data is unavailable
    so the model pipeline is not disrupted during backfill.
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    def extract(self, matches: list[Match]) -> dict[int, dict]:
        result: dict[int, dict] = {}
        found = 0

        for match in matches:
            snap: WeatherSnapshot | None = (
                self._db.query(WeatherSnapshot)
                .filter(WeatherSnapshot.match_id == match.id)
                .first()
            )

            if snap is None or snap.temperature_c is None:
                result[match.id] = dict(_NULL_FEATURES)
                continue

            found += 1
            scoring_index = _compute_scoring_index(snap)

            result[match.id] = {
                "weather_temp_c": snap.temperature_c,
                "weather_wind_kmh": snap.wind_speed_kmh,
                "weather_precip_mm": snap.precipitation_mm,
                "weather_is_raining": int(snap.is_raining or 0),
                "weather_is_high_wind": int(snap.is_high_wind or 0),
                "weather_is_extreme_heat": int(snap.is_extreme_heat or 0),
                "weather_scoring_index": round(scoring_index, 4),
            }

        logger.debug(
            f"WeatherExtractor: {found}/{len(matches)} matches have weather data."
        )
        return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compute_scoring_index(snap: WeatherSnapshot) -> float:
    """
    Compute 0.5-1.0 scoring condition index.
    1.0 = perfect conditions, lower = harder to score.
    """
    index = 1.0

    # Wind penalty: each 10 km/h above 20 km/h removes 3%
    wind = snap.wind_speed_kmh or 0.0
    if wind > _WIND_THRESHOLD_KMH:
        excess = wind - _WIND_THRESHOLD_KMH
    else:
        excess = 0.0
    wind_penalty = (excess / 10.0) * _WIND_PENALTY_PER_10KMH

    # Rain penalty
    rain_penalty = _RAIN_PENALTY if snap.is_raining else 0.0

    # Extreme heat penalty
    heat_penalty = _HEAT_PENALTY if snap.is_extreme_heat else 0.0

    index = index - wind_penalty - rain_penalty - heat_penalty
    return max(_INDEX_MIN, min(1.0, index))
