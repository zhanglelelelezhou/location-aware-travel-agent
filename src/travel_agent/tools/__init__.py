from travel_agent.tools.base import ToolRegistry
from travel_agent.tools.mock import (
    MockPoiSearchTool,
    MockTranslateTool,
    MockTravelKnowledgeTool,
    MockWeatherTool,
)


def build_mock_registry() -> ToolRegistry:
    return ToolRegistry(
        [
            MockPoiSearchTool(),
            MockWeatherTool(),
            MockTranslateTool(),
            MockTravelKnowledgeTool(),
        ]
    )


__all__ = ["ToolRegistry", "build_mock_registry"]

