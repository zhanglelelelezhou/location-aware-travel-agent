from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass
from typing import Any

from mcp import Client, StdioServerParameters

from travel_agent.tools.base import ToolRegistry
from travel_agent.tools.knowledge import build_knowledge_tool_from_env
from travel_agent.tools.mock import MockTranslateTool


class MCPToolError(RuntimeError):
    """Normalize MCP transport and protocol failures at the tool boundary."""


@dataclass(frozen=True)
class MCPToolAdapter:
    name: str
    description: str
    target: Any
    timeout_seconds: float = 20.0

    def invoke(self, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            return asyncio.run(self._invoke(arguments))
        except MCPToolError:
            raise
        except Exception as exc:
            raise MCPToolError(f"MCP call to {self.name} failed: {exc}") from exc

    async def _invoke(self, arguments: dict[str, Any]) -> dict[str, Any]:
        async with Client(
            self.target,
            raise_exceptions=True,
            read_timeout_seconds=self.timeout_seconds,
        ) as client:
            result = await client.call_tool(self.name, arguments)
        return self._parse_result(result)

    async def invoke_with_client(
        self, client: Any, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        result = await client.call_tool(self.name, arguments)
        return self._parse_result(result)

    def _parse_result(self, result: Any) -> dict[str, Any]:
        if result.is_error:
            messages = [
                block.text
                for block in result.content
                if getattr(block, "text", None)
            ]
            detail = "; ".join(messages) or "server returned an unspecified tool error"
            raise MCPToolError(f"MCP tool {self.name} returned an error: {detail}")
        if not isinstance(result.structured_content, dict):
            raise MCPToolError(
                f"MCP tool {self.name} did not return structured content"
            )
        return dict(result.structured_content)


class MCPToolRegistry(ToolRegistry):
    def __init__(
        self,
        tools: list[Any],
        *,
        target: Any,
        timeout_seconds: float,
        provider: str,
    ) -> None:
        super().__init__(tools, provider=provider)
        self.target = target
        self.timeout_seconds = timeout_seconds

    def invoke_many(
        self, calls: list[tuple[str, dict[str, Any]]]
    ) -> list[dict[str, Any] | Exception]:
        if not calls:
            return []
        if not any(
            isinstance(self._get_tool(name), MCPToolAdapter) for name, _ in calls
        ):
            return super().invoke_many(calls)
        try:
            return asyncio.run(self._invoke_many(calls))
        except Exception as exc:  # noqa: BLE001
            error = MCPToolError(f"MCP session failed: {exc}")
            outcomes: list[dict[str, Any] | Exception] = []
            for name, arguments in calls:
                try:
                    tool = self._get_tool(name)
                    outcomes.append(
                        error
                        if isinstance(tool, MCPToolAdapter)
                        else tool.invoke(arguments)
                    )
                except Exception as local_exc:  # noqa: BLE001
                    outcomes.append(local_exc)
            return outcomes

    async def _invoke_many(
        self, calls: list[tuple[str, dict[str, Any]]]
    ) -> list[dict[str, Any] | Exception]:
        outcomes: list[dict[str, Any] | Exception] = []
        async with Client(
            self.target,
            raise_exceptions=True,
            read_timeout_seconds=self.timeout_seconds,
        ) as client:
            for name, arguments in calls:
                try:
                    tool = self._get_tool(name)
                    if isinstance(tool, MCPToolAdapter):
                        outcomes.append(
                            await tool.invoke_with_client(client, arguments)
                        )
                    else:
                        outcomes.append(tool.invoke(arguments))
                except Exception as exc:  # noqa: BLE001
                    outcomes.append(exc)
        return outcomes


def build_mcp_registry(
    target: Any | None = None,
    *,
    provider: str | None = None,
    timeout_seconds: float | None = None,
) -> MCPToolRegistry:
    resolved_target = target
    resolved_provider = provider
    if resolved_target is None:
        server_url = os.getenv("MCP_SERVER_URL", "").strip()
        if server_url:
            resolved_target = server_url
            resolved_provider = resolved_provider or "mcp-http"
        else:
            server_provider = os.getenv("MCP_SERVER_PROVIDER", "open-data").lower()
            if server_provider not in {"mock", "open-data"}:
                raise ValueError(
                    "MCP_SERVER_PROVIDER must be either 'mock' or 'open-data'"
                )
            resolved_target = StdioServerParameters(
                command=sys.executable,
                args=[
                    "-m",
                    "travel_agent.mcp_server",
                    "--provider",
                    server_provider,
                ],
            )
            resolved_provider = resolved_provider or f"mcp-stdio:{server_provider}"

    timeout = timeout_seconds or float(os.getenv("MCP_TIMEOUT_SECONDS", "20"))
    return MCPToolRegistry(
        [
            MCPToolAdapter(
                name="search_poi",
                description="Search nearby places through an MCP server.",
                target=resolved_target,
                timeout_seconds=timeout,
            ),
            MCPToolAdapter(
                name="get_weather",
                description="Get current weather through an MCP server.",
                target=resolved_target,
                timeout_seconds=timeout,
            ),
            MockTranslateTool(),
            build_knowledge_tool_from_env(),
        ],
        target=resolved_target,
        timeout_seconds=timeout,
        provider=resolved_provider or "mcp",
    )


__all__ = [
    "MCPToolAdapter",
    "MCPToolError",
    "MCPToolRegistry",
    "build_mcp_registry",
]
