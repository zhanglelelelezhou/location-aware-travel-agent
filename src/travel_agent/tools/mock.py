from __future__ import annotations

from typing import Any

from travel_agent.tools.weather import WeatherObservation


class MockPoiSearchTool:
    name = "search_poi"
    description = "Search nearby points of interest with user constraints."

    def invoke(self, arguments: dict[str, Any]) -> dict[str, Any]:
        location = arguments.get("location") or "当前位置"
        preferences = arguments.get("preferences") or []
        return {
            "location": location,
            "results": [
                {
                    "name": "Green Table Umeda",
                    "category": "restaurant",
                    "walking_minutes": 8,
                    "supports": preferences or ["vegetarian options"],
                    "source": "mock://poi/osaka/green-table-umeda",
                },
                {
                    "name": "Osaka Station City",
                    "category": "attraction",
                    "walking_minutes": 2,
                    "source": "mock://poi/osaka/station-city",
                },
            ],
        }


class MockWeatherTool:
    name = "get_weather"
    description = "Get weather conditions for itinerary planning."

    def invoke(self, arguments: dict[str, Any]) -> dict[str, Any]:
        location = arguments.get("location") or "当前位置"
        return WeatherObservation(
            location=location,
            resolved_location=location,
            condition="light rain",
            temperature_c=21,
            apparent_temperature_c=20,
            precipitation_mm=0.5,
            wind_speed_kmh=12,
            weather_code=61,
            observed_at="2026-01-01T12:00",
            timezone="Asia/Tokyo",
            resolution_method="mock",
            provider="mock",
            source="mock://weather/current",
        ).model_dump(exclude_none=True)


class MockTranslateTool:
    name = "translate_phrase"
    description = "Translate a travel phrase into the target language."

    def invoke(self, arguments: dict[str, Any]) -> dict[str, Any]:
        target = arguments.get("target_language", "ja")
        preferences = "、".join(arguments.get("preferences") or [])
        if target == "ja" and "素食" in preferences:
            translated = "ベジタリアン向けの料理はありますか？"
        else:
            translated = "旅行中に使う翻訳文です。" if target == "ja" else "Travel phrase."
        return {
            "target_language": target,
            "translated_text": translated,
            "provider": "mock",
        }


class MockTravelKnowledgeTool:
    name = "search_travel_knowledge"
    description = "Retrieve grounded travel and food-safety guidance."

    def invoke(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            "passages": [
                {
                    "text": "有严重食物过敏时，应向店员确认配料和交叉污染风险。",
                    "source": "mock://knowledge/food-allergy/001",
                }
            ]
        }
