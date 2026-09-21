import os

from dotenv import load_dotenv

from travel_agent.tools.base import ToolRegistry
from travel_agent.tools.mock import (
    MockPoiSearchTool,
    MockTranslateTool,
    MockTravelKnowledgeTool,
    MockWeatherTool,
)
from travel_agent.tools.open_meteo import OpenMeteoWeatherTool


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
    if selected != "open-meteo":
        raise ValueError(f"Unsupported tool provider: {selected}")
    return ToolRegistry(
        [
            MockPoiSearchTool(),
            OpenMeteoWeatherTool(
                timeout_seconds=float(os.getenv("WEATHER_TIMEOUT_SECONDS", "8"))
            ),
            MockTranslateTool(),
            MockTravelKnowledgeTool(),
        ],
        provider="open-meteo",
    )


__all__ = ["ToolRegistry", "build_mock_registry", "build_tool_registry_from_env"]
