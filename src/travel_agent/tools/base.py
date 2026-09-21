from __future__ import annotations

from typing import Any, Protocol


class Tool(Protocol):
    name: str
    description: str

    def invoke(self, arguments: dict[str, Any]) -> dict[str, Any]: ...


class ToolRegistry:
    def __init__(self, tools: list[Tool], *, provider: str = "custom") -> None:
        self._tools = {tool.name: tool for tool in tools}
        self.provider = provider

    def invoke(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            tool = self._tools[name]
        except KeyError as exc:
            raise ValueError(f"Unknown tool: {name}") from exc
        return tool.invoke(arguments)

    @property
    def names(self) -> list[str]:
        return sorted(self._tools)
