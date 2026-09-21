from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class WeatherObservation(BaseModel):
    """Provider-neutral output contract for the get_weather tool."""

    model_config = ConfigDict(extra="forbid")

    location: str
    resolved_location: str
    condition: str
    temperature_c: float
    apparent_temperature_c: float | None = None
    precipitation_mm: float | None = None
    wind_speed_kmh: float | None = None
    weather_code: int | None = None
    observed_at: str | None = None
    timezone: str | None = None
    resolution_method: str
    provider: str
    source: str
