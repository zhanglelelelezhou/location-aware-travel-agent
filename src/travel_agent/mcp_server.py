from __future__ import annotations

import argparse
from typing import Annotated, Any, Literal

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from travel_agent.tools.base import Tool
from travel_agent.tools.open_meteo import OpenMeteoWeatherTool
from travel_agent.tools.overpass import OverpassPoiSearchTool
from travel_agent.tools.poi import PoiSearchResult
from travel_agent.tools.weather import WeatherObservation

TOOL_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)

PoiCategory = Literal[
    "restaurant",
    "cafe",
    "museum",
    "attraction",
    "park",
    "place_of_worship",
]


def create_mcp_server(
    *, weather_tool: Tool | None = None, poi_tool: Tool | None = None
) -> MCPServer:
    weather = weather_tool or OpenMeteoWeatherTool()
    poi = poi_tool or OverpassPoiSearchTool()
    server = MCPServer(
        "location-aware-travel-tools",
        title="Location-Aware Travel Tools",
        description="Read-only, evidence-aware weather and nearby-place tools.",
        instructions=(
            "Prefer trusted device coordinates. Never infer that an unverified preference "
            "is satisfied. Preserve provider attribution and source links in user-facing output."
        ),
        version="0.1.0",
    )

    @server.tool(
        name="get_weather",
        annotations=TOOL_ANNOTATIONS,
        structured_output=True,
    )
    def get_weather(
        location: str,
        latitude: Annotated[float | None, Field(ge=-90, le=90)] = None,
        longitude: Annotated[float | None, Field(ge=-180, le=180)] = None,
    ) -> WeatherObservation:
        """Get current weather, preferring a trusted latitude/longitude pair."""

        result = weather.invoke(
            {
                "location": location,
                "latitude": latitude,
                "longitude": longitude,
            }
        )
        return WeatherObservation.model_validate(result)

    @server.tool(
        name="search_poi",
        annotations=TOOL_ANNOTATIONS,
        structured_output=True,
    )
    def search_poi(
        location: str,
        latitude: Annotated[float, Field(ge=-90, le=90)],
        longitude: Annotated[float, Field(ge=-180, le=180)],
        categories: list[PoiCategory] | None = None,
        preferences: list[str] | None = None,
        radius_m: Annotated[int, Field(ge=100, le=5000)] = 1500,
        limit: Annotated[int, Field(ge=1, le=10)] = 5,
    ) -> PoiSearchResult:
        """Search nearby POIs with bounded categories and evidence-aware preferences."""

        arguments: dict[str, Any] = {
            "location": location,
            "latitude": latitude,
            "longitude": longitude,
            "preferences": preferences or [],
            "radius_m": radius_m,
            "limit": limit,
        }
        if categories is not None:
            arguments["categories"] = categories
        result = poi.invoke(arguments)
        return PoiSearchResult.model_validate(result)

    return server


mcp = create_mcp_server()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the travel-tools MCP server.")
    parser.add_argument(
        "--transport", choices=["stdio", "streamable-http"], default="stdio"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()

    try:
        if args.transport == "stdio":
            mcp.run()
        else:
            mcp.run(transport="streamable-http", host=args.host, port=args.port)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
