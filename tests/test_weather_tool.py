from __future__ import annotations

import httpx
import pytest

from travel_agent.tools.mock import MockWeatherTool
from travel_agent.tools.open_meteo import OpenMeteoWeatherTool, WeatherToolError
from travel_agent.tools.weather import WeatherObservation


def test_mock_and_live_weather_share_output_contract() -> None:
    mock_result = MockWeatherTool().invoke({"location": "大阪"})

    observation = WeatherObservation.model_validate(mock_result)

    assert observation.provider == "mock"
    assert observation.temperature_c == 21


def test_open_meteo_resolves_location_and_returns_current_weather() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "geocoding-api.open-meteo.com":
            assert request.url.params["name"] == "东京"
            assert request.url.params["count"] == "5"
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "name": "东京",
                            "latitude": 35.6895,
                            "longitude": 139.6917,
                            "admin1": "东京都",
                            "country": "日本",
                        }
                    ]
                },
            )
        assert request.url.host == "api.open-meteo.com"
        assert request.url.params["latitude"] == "35.6895"
        assert request.url.params["timezone"] == "auto"
        assert "weather_code" in request.url.params["current"]
        return httpx.Response(
            200,
            json={
                "timezone": "Asia/Tokyo",
                "current": {
                    "time": "2026-09-21T12:00",
                    "temperature_2m": 24.5,
                    "apparent_temperature": 25.1,
                    "precipitation": 0.0,
                    "weather_code": 2,
                    "wind_speed_10m": 8.4,
                },
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = OpenMeteoWeatherTool(client=client).invoke({"location": "东京"})
    observation = WeatherObservation.model_validate(result)

    assert observation.provider == "open-meteo"
    assert observation.resolved_location == "东京, 东京都, 日本"
    assert observation.condition == "partly cloudy"
    assert observation.temperature_c == 24.5
    assert observation.resolution_method == "geocoding"
    assert observation.source.startswith("https://api.open-meteo.com/v1/forecast?")


def test_open_meteo_prefers_device_coordinates_over_ambiguous_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.open-meteo.com"
        assert request.url.params["latitude"] == "35.6895"
        assert request.url.params["longitude"] == "139.6917"
        return httpx.Response(
            200,
            json={
                "timezone": "Asia/Tokyo",
                "current": {
                    "time": "2026-09-21T12:00",
                    "temperature_2m": 23,
                    "apparent_temperature": 24,
                    "precipitation": 0,
                    "weather_code": 0,
                    "wind_speed_10m": 5,
                },
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = OpenMeteoWeatherTool(client=client).invoke(
        {"location": "东京", "latitude": 35.6895, "longitude": 139.6917}
    )

    assert result["resolved_location"] == "东京"
    assert result["resolution_method"] == "coordinates"
    assert result["condition"] == "clear sky"


def test_open_meteo_rejects_missing_location() -> None:
    with pytest.raises(ValueError, match="non-empty location"):
        OpenMeteoWeatherTool().invoke({})


def test_open_meteo_reports_unresolved_location() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"results": []})
        )
    )

    with pytest.raises(WeatherToolError, match="could not be resolved"):
        OpenMeteoWeatherTool(client=client).invoke({"location": "不存在的地点"})


def test_open_meteo_rejects_ambiguous_text_location() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "name": "东京",
                            "latitude": 32.2,
                            "longitude": 119.2,
                            "feature_code": "PPL",
                        },
                        {
                            "name": "东京",
                            "latitude": 28.0,
                            "longitude": 119.4,
                            "feature_code": "PPL",
                        },
                    ]
                },
            )
        )
    )

    with pytest.raises(WeatherToolError, match="ambiguous; provide coordinates"):
        OpenMeteoWeatherTool(client=client).invoke({"location": "东京"})


def test_open_meteo_normalizes_provider_failure() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(503, text="down"))
    )

    with pytest.raises(WeatherToolError, match="provider request failed"):
        OpenMeteoWeatherTool(client=client).invoke({"location": "东京"})
