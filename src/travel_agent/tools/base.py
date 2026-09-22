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
        tool = self._get_tool(name)
        return tool.invoke(arguments)

    def invoke_many(
        self, calls: list[tuple[str, dict[str, Any]]]
    ) -> list[dict[str, Any] | Exception]:
        outcomes: list[dict[str, Any] | Exception] = []
        for name, arguments in calls:
            try:
                outcomes.append(self.invoke(name, arguments))
            except Exception as exc:  # noqa: BLE001
                outcomes.append(exc)
        return outcomes

    def _get_tool(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ValueError(f"Unknown tool: {name}") from exc

    @property
    def names(self) -> list[str]:
        return sorted(self._tools)
