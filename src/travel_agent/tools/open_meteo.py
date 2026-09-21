from __future__ import annotations

from typing import Any

import httpx

from travel_agent.tools.weather import WeatherObservation

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


class WeatherToolError(RuntimeError):
    """Normalized boundary error for the weather provider."""


class OpenMeteoWeatherTool:
    name = "get_weather"
    description = "Resolve a place name and retrieve current weather from Open-Meteo."

    def __init__(
        self,
        *,
        timeout_seconds: float = 8.0,
        client: httpx.Client | None = None,
        geocoding_url: str = GEOCODING_URL,
        forecast_url: str = FORECAST_URL,
    ) -> None:
        self.client = client or httpx.Client(timeout=timeout_seconds)
        self.geocoding_url = geocoding_url
        self.forecast_url = forecast_url

    def invoke(self, arguments: dict[str, Any]) -> dict[str, Any]:
        location = arguments.get("location")
        if not isinstance(location, str) or not location.strip():
            raise ValueError("get_weather requires a non-empty location")
        location = location.strip()

        provided_latitude = arguments.get("latitude")
        provided_longitude = arguments.get("longitude")
        if (provided_latitude is None) != (provided_longitude is None):
            raise ValueError("latitude and longitude must be provided together")

        if provided_latitude is not None and provided_longitude is not None:
            latitude = _coordinate(provided_latitude, "latitude", -90, 90)
            longitude = _coordinate(provided_longitude, "longitude", -180, 180)
            resolved_name = location
            resolution_method = "coordinates"
        else:
            geocoding, _ = self._get_json(
                self.geocoding_url,
                params={
                    "name": location,
                    "count": 5,
                    "language": "zh",
                    "format": "json",
                },
            )
            place = _select_place(geocoding.get("results"), location)
            latitude = _number(place.get("latitude"), "latitude")
            longitude = _number(place.get("longitude"), "longitude")
            resolved_name = str(place.get("name") or location)
            admin1 = place.get("admin1")
            country = place.get("country")
            qualifiers = [str(item) for item in (admin1, country) if item]
            if qualifiers:
                resolved_name = ", ".join([resolved_name, *qualifiers])
            resolution_method = "geocoding"

        forecast, source = self._get_json(
            self.forecast_url,
            params={
                "latitude": latitude,
                "longitude": longitude,
                "current": (
                    "temperature_2m,apparent_temperature,precipitation,"
                    "weather_code,wind_speed_10m"
                ),
                "timezone": "auto",
            },
        )
        current = forecast.get("current")
        if not isinstance(current, dict):
            raise WeatherToolError("weather provider returned no current conditions")

        weather_code = int(_number(current.get("weather_code"), "weather_code"))
        observation = WeatherObservation(
            location=location,
            resolved_location=resolved_name,
            condition=describe_weather_code(weather_code),
            temperature_c=_number(current.get("temperature_2m"), "temperature_2m"),
            apparent_temperature_c=_optional_number(current.get("apparent_temperature")),
            precipitation_mm=_optional_number(current.get("precipitation")),
            wind_speed_kmh=_optional_number(current.get("wind_speed_10m")),
            weather_code=weather_code,
            observed_at=_optional_string(current.get("time")),
            timezone=_optional_string(forecast.get("timezone")),
            resolution_method=resolution_method,
            provider="open-meteo",
            source=source,
        )
        return observation.model_dump(exclude_none=True)

    def _get_json(
        self, url: str, *, params: dict[str, Any]
    ) -> tuple[dict[str, Any], str]:
        try:
            response = self.client.get(url, params=params)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise WeatherToolError("weather provider timed out") from exc
        except httpx.HTTPError as exc:
            raise WeatherToolError("weather provider request failed") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise WeatherToolError("weather provider returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise WeatherToolError("weather provider returned an invalid payload")
        return payload, str(response.request.url)


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise WeatherToolError(f"weather provider omitted numeric field: {field}")
    return float(value)


def _coordinate(value: object, field: str, minimum: float, maximum: float) -> float:
    coordinate = _number(value, field)
    if not minimum <= coordinate <= maximum:
        raise ValueError(f"{field} must be between {minimum} and {maximum}")
    return coordinate


def _select_place(results: object, query: str) -> dict[str, Any]:
    if not isinstance(results, list) or not results:
        raise WeatherToolError(f"location could not be resolved: {query}")
    places = [item for item in results if isinstance(item, dict)]
    if not places:
        raise WeatherToolError("geocoding provider returned an invalid result")

    def rank(place: dict[str, Any]) -> tuple[int, int]:
        feature = str(place.get("feature_code") or "")
        feature_rank = {"PPLC": 4, "PPLA": 3, "PPLA2": 2, "PPL": 1}.get(feature, 0)
        population = place.get("population")
        return feature_rank, int(population) if isinstance(population, int) else 0

    places.sort(key=rank, reverse=True)
    top = places[0]
    if len(places) > 1:
        exact_matches = [
            place
            for place in places
            if str(place.get("name") or "").casefold() == query.casefold()
        ]
        if len(exact_matches) > 1 and rank(top)[1] == 0:
            raise WeatherToolError(
                f"location is ambiguous; provide coordinates: {query}"
            )
    return top


def _optional_number(value: object) -> float | None:
    if value is None:
        return None
    return _number(value, "optional weather value")


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def describe_weather_code(code: int) -> str:
    if code == 0:
        return "clear sky"
    if code in {1, 2, 3}:
        return {1: "mainly clear", 2: "partly cloudy", 3: "overcast"}[code]
    if code in {45, 48}:
        return "fog"
    if code in {51, 53, 55, 56, 57}:
        return "drizzle"
    if code in {61, 63, 65, 66, 67}:
        return "rain"
    if code in {71, 73, 75, 77}:
        return "snow"
    if code in {80, 81, 82}:
        return "rain showers"
    if code in {85, 86}:
        return "snow showers"
    if code in {95, 96, 99}:
        return "thunderstorm"
    return "unknown"
