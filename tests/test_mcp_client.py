from __future__ import annotations

import sys

import pytest
from mcp import StdioServerParameters

from travel_agent.graph import run_agent
from travel_agent.mcp_server import create_mcp_server
from travel_agent.models import TravelRequest
from travel_agent.tools.mcp import MCPToolError, build_mcp_registry
from travel_agent.tools.mock import MockPoiSearchTool, MockWeatherTool


def test_agent_executes_plan_through_in_memory_mcp_client() -> None:
    server = create_mcp_server(
        weather_tool=MockWeatherTool(), poi_tool=MockPoiSearchTool()
    )
    registry = build_mcp_registry(server, provider="mcp-memory")

    response = run_agent(
        TravelRequest(
            text="帮我安排东京半日景点行程",
            location="东京",
            latitude=35.6895,
            longitude=139.6917,
        ),
        registry=registry,
    )

    assert registry.provider == "mcp-memory"
    assert [execution.name for execution in response.trace.executions] == [
        "search_poi",
        "get_weather",
    ]
    assert all(
        execution.output is not None and execution.output["provider"] == "mock"
        for execution in response.trace.executions
    )


def test_agent_batches_a_multi_tool_plan_into_one_mcp_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = create_mcp_server(
        weather_tool=MockWeatherTool(), poi_tool=MockPoiSearchTool()
    )
    registry = build_mcp_registry(server, provider="mcp-counted")
    original = registry._invoke_many
    batches: list[list[tuple[str, dict[str, object]]]] = []

    async def counted(calls: list[tuple[str, dict[str, object]]]):
        batches.append(calls)
        return await original(calls)

    monkeypatch.setattr(registry, "_invoke_many", counted)

    response = run_agent(
        TravelRequest(
            text="帮我安排东京半日景点行程",
            location="东京",
            latitude=35.6895,
            longitude=139.6917,
        ),
        registry=registry,
    )

    assert len(response.trace.executions) == 2
    assert [[name for name, _ in batch] for batch in batches] == [
        ["search_poi", "get_weather"]
    ]


def test_agent_calls_mock_mcp_server_over_real_stdio_subprocess() -> None:
    target = StdioServerParameters(
        command=sys.executable,
        args=["-m", "travel_agent.mcp_server", "--provider", "mock"],
    )
    registry = build_mcp_registry(target, provider="mcp-stdio:test")

    response = run_agent(
        TravelRequest(
            text="东京现在天气如何",
            location="东京",
            latitude=35.6895,
            longitude=139.6917,
        ),
        registry=registry,
    )

    execution = response.trace.executions[0]
    assert execution.error is None
    assert execution.output is not None
    assert execution.output["provider"] == "mock"


def test_mcp_tool_error_is_normalized_for_invalid_protocol_arguments() -> None:
    server = create_mcp_server(
        weather_tool=MockWeatherTool(), poi_tool=MockPoiSearchTool()
    )
    registry = build_mcp_registry(server)

    with pytest.raises(MCPToolError, match="returned an error"):
        registry.invoke(
            "search_poi",
            {
                "location": "东京",
                "latitude": 35.6895,
                "longitude": 139.6917,
                "radius_m": 100_000,
            },
        )


def test_mcp_session_failure_does_not_block_local_tools() -> None:
    registry = build_mcp_registry(object(), provider="broken-mcp")

    outcomes = registry.invoke_many(
        [
            (
                "get_weather",
                {
                    "location": "东京",
                    "latitude": 35.6895,
                    "longitude": 139.6917,
                },
            ),
            (
                "translate_phrase",
                {"text": "我对花生过敏", "target_language": "ja"},
            ),
        ]
    )

    assert isinstance(outcomes[0], MCPToolError)
    assert isinstance(outcomes[1], dict)
    assert outcomes[1]["translated_text"]
