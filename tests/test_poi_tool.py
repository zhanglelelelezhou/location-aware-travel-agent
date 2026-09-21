from __future__ import annotations

from urllib.parse import parse_qs

import httpx
import pytest

from travel_agent.tools import build_tool_registry_from_env
from travel_agent.tools.mock import MockPoiSearchTool
from travel_agent.tools.overpass import OverpassPoiSearchTool, PoiToolError
from travel_agent.tools.poi import PoiSearchResult


def test_mock_and_overpass_poi_share_output_contract() -> None:
    result = MockPoiSearchTool().invoke(
        {"location": "大阪", "latitude": 34.7, "longitude": 135.5}
    )

    parsed = PoiSearchResult.model_validate(result)

    assert parsed.provider == "mock"
    assert parsed.results[0].walking_minutes == 8


def test_overpass_returns_only_preference_evidenced_places() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        query = parse_qs(request.content.decode())["data"][0]
        assert "around:1500,35.689500,139.691700" in query
        assert '["amenity"="restaurant"]' in query
        assert "out center tags 60" in query
        return httpx.Response(
            200,
            json={
                "elements": [
                    {
                        "type": "node",
                        "id": 101,
                        "lat": 35.6900,
                        "lon": 139.6920,
                        "tags": {
                            "name": "Verified Vegan Cafe",
                            "amenity": "restaurant",
                            "diet:vegan": "yes",
                        },
                    },
                    {
                        "type": "node",
                        "id": 102,
                        "lat": 35.6901,
                        "lon": 139.6921,
                        "tags": {"name": "Unverified Restaurant", "amenity": "restaurant"},
                    },
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = OverpassPoiSearchTool(client=client).invoke(
        {
            "location": "东京",
            "latitude": 35.6895,
            "longitude": 139.6917,
            "categories": ["restaurant"],
            "preferences": ["纯素"],
        }
    )
    parsed = PoiSearchResult.model_validate(result)

    assert [item.name for item in parsed.results] == ["Verified Vegan Cafe"]
    assert parsed.results[0].supports == ["vegan"]
    assert parsed.verified_preferences == ["vegan"]
    assert parsed.unverified_preferences == []
    assert parsed.results[0].source == "https://www.openstreetmap.org/node/101"


def test_overpass_marks_preferences_without_osm_evidence_as_unverified() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "elements": [
                        {
                            "type": "node",
                            "id": 103,
                            "lat": 35.69,
                            "lon": 139.692,
                            "tags": {"name": "Quiet Cafe", "amenity": "cafe"},
                        }
                    ]
                },
            )
        )
    )

    result = OverpassPoiSearchTool(client=client).invoke(
        {
            "location": "东京",
            "latitude": 35.6895,
            "longitude": 139.6917,
            "categories": ["cafe"],
            "preferences": ["安静"],
        }
    )

    assert result["verified_preferences"] == []
    assert result["unverified_preferences"] == ["安静"]
    assert result["results"][0]["name"] == "Quiet Cafe"


def test_overpass_parses_way_center_and_sorts_by_distance() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "elements": [
                        {
                            "type": "way",
                            "id": 201,
                            "center": {"lat": 35.7000, "lon": 139.7000},
                            "tags": {"name:en": "City Museum", "tourism": "museum"},
                        },
                        {
                            "type": "node",
                            "id": 202,
                            "lat": 35.6896,
                            "lon": 139.6918,
                            "tags": {"name": "Nearby Museum", "tourism": "museum"},
                        },
                    ]
                },
            )
        )
    )

    result = OverpassPoiSearchTool(client=client).invoke(
        {
            "location": "东京",
            "latitude": 35.6895,
            "longitude": 139.6917,
            "categories": ["museum"],
        }
    )

    assert [item["name"] for item in result["results"]] == [
        "Nearby Museum",
        "City Museum",
    ]


def test_overpass_requires_trusted_coordinates() -> None:
    with pytest.raises(TypeError, match="requires numeric latitude"):
        OverpassPoiSearchTool().invoke({"location": "东京"})


def test_overpass_rejects_unknown_category_before_request() -> None:
    with pytest.raises(ValueError, match="unsupported POI category"):
        OverpassPoiSearchTool().invoke(
            {
                "location": "东京",
                "latitude": 35.6895,
                "longitude": 139.6917,
                "categories": ["anything];out;"],
            }
        )


def test_overpass_normalizes_provider_failure() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(429, text="busy"))
    )

    with pytest.raises(PoiToolError, match="provider request failed"):
        OverpassPoiSearchTool(client=client).invoke(
            {"location": "东京", "latitude": 35.6895, "longitude": 139.6917}
        )


def test_open_data_registry_uses_both_live_adapters(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_PROVIDER", "open-data")

    registry = build_tool_registry_from_env()

    assert registry.provider == "open-data"
    assert registry.names == [
        "get_weather",
        "search_poi",
        "search_travel_knowledge",
        "translate_phrase",
    ]
