from __future__ import annotations

import asyncio
import sys

from mcp import Client, StdioServerParameters

from travel_agent.mcp_server import create_mcp_server
from travel_agent.tools.mock import MockPoiSearchTool, MockWeatherTool


def test_mcp_discovers_and_calls_travel_tools_in_process() -> None:
    async def scenario() -> None:
        server = create_mcp_server(
            weather_tool=MockWeatherTool(), poi_tool=MockPoiSearchTool()
        )
        async with Client(server, raise_exceptions=True) as client:
            listed = await client.list_tools()
            assert {tool.name for tool in listed.tools} == {"get_weather", "search_poi"}

            weather = await client.call_tool(
                "get_weather",
                {"location": "东京", "latitude": 35.6895, "longitude": 139.6917},
            )
            assert not weather.is_error
            assert weather.structured_content is not None
            assert weather.structured_content["provider"] == "mock"
            assert weather.structured_content["temperature_c"] == 21

            poi = await client.call_tool(
                "search_poi",
                {
                    "location": "东京站",
                    "latitude": 35.6812,
                    "longitude": 139.7671,
                    "categories": ["restaurant"],
                    "preferences": ["素食"],
                },
            )
            assert not poi.is_error
            assert poi.structured_content is not None
            assert poi.structured_content["results"][0]["name"] == "Green Table Umeda"

    asyncio.run(scenario())


def test_mcp_schema_exposes_bounds_and_read_only_annotations() -> None:
    async def scenario() -> None:
        server = create_mcp_server(
            weather_tool=MockWeatherTool(), poi_tool=MockPoiSearchTool()
        )
        async with Client(server, raise_exceptions=True) as client:
            listed = await client.list_tools()
            tools = {tool.name: tool for tool in listed.tools}
            poi = tools["search_poi"]

            assert poi.annotations is not None
            assert poi.annotations.read_only_hint is True
            assert poi.annotations.destructive_hint is False
            assert poi.input_schema["properties"]["radius_m"]["maximum"] == 5000
            assert poi.input_schema["properties"]["limit"]["maximum"] == 10
            category_schema = poi.input_schema["properties"]["categories"]
            assert "restaurant" in str(category_schema)

    asyncio.run(scenario())


def test_mcp_protocol_rejects_invalid_arguments_before_adapter_call() -> None:
    async def scenario() -> None:
        server = create_mcp_server(
            weather_tool=MockWeatherTool(), poi_tool=MockPoiSearchTool()
        )
        async with Client(server, raise_exceptions=True) as client:
            result = await client.call_tool(
                "search_poi",
                {
                    "location": "东京站",
                    "latitude": 35.6812,
                    "longitude": 139.7671,
                    "categories": ["arbitrary_query"],
                    "radius_m": 100000,
                },
            )

            assert result.is_error

    asyncio.run(scenario())


def test_mcp_stdio_subprocess_exposes_tools() -> None:
    async def scenario() -> None:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "travel_agent.mcp_server"],
        )
        async with Client(parameters) as client:
            listed = await client.list_tools()
            assert {tool.name for tool in listed.tools} == {"get_weather", "search_poi"}
            assert client.protocol_version is not None

    asyncio.run(scenario())
