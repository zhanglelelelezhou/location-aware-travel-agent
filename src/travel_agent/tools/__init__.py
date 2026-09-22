import os

from dotenv import load_dotenv

from travel_agent.tools.base import ToolRegistry
from travel_agent.tools.knowledge import build_knowledge_tool_from_env
from travel_agent.tools.mcp import build_mcp_registry
from travel_agent.tools.mock import (
    MockPoiSearchTool,
    MockTranslateTool,
    MockTravelKnowledgeTool,
    MockWeatherTool,
)
from travel_agent.tools.open_meteo import OpenMeteoWeatherTool
from travel_agent.tools.overpass import OverpassPoiSearchTool


def build_mock_registry() -> ToolRegistry:
    return ToolRegistry(
        [
            MockPoiSearchTool(),
            MockWeatherTool(),
            MockTranslateTool(),
            MockTravelKnowledgeTool(),
        ],
        provider="mock",
    )


def build_tool_registry_from_env(kind: str | None = None) -> ToolRegistry:
    load_dotenv()
    selected = (kind or os.getenv("AGENT_PROVIDER", "mock")).lower()
    if selected == "mock":
        return build_mock_registry()
    if selected == "mcp":
        return build_mcp_registry()
    if selected not in {"open-meteo", "open-data"}:
        raise ValueError(f"Unsupported tool provider: {selected}")
    return ToolRegistry(
        [
            (
                OverpassPoiSearchTool(
                    timeout_seconds=float(os.getenv("POI_TIMEOUT_SECONDS", "12"))
                )
                if selected == "open-data"
                else MockPoiSearchTool()
            ),
            OpenMeteoWeatherTool(
                timeout_seconds=float(os.getenv("WEATHER_TIMEOUT_SECONDS", "8"))
            ),
            MockTranslateTool(),
            build_knowledge_tool_from_env(),
        ],
        provider=selected,
    )


__all__ = [
    "ToolRegistry",
    "build_mcp_registry",
    "build_mock_registry",
    "build_tool_registry_from_env",
]
