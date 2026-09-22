from __future__ import annotations

import json

from travel_agent.models import AgentEvent, ChatRequest
from travel_agent.planner import RulePlanner
from travel_agent.session import ConversationService
from travel_agent.streaming import encode_sse, stream_conversation
from travel_agent.tools import build_mock_registry
from travel_agent.tools.base import ToolRegistry
from travel_agent.tools.mock import (
    MockPoiSearchTool,
    MockTranslateTool,
    MockTravelKnowledgeTool,
)


def parse_frames(frames: list[str]) -> list[dict[str, object]]:
    parsed: list[dict[str, object]] = []
    for frame in frames:
        if frame.startswith(":"):
            continue
        fields = {
            key: value.strip()
            for line in frame.strip().splitlines()
            for key, value in [line.split(":", 1)]
        }
        payload = json.loads(fields["data"])
        assert payload["type"] == fields["event"]
        assert str(payload["sequence"]) == fields["id"]
        parsed.append(payload)
    return parsed


def build_service(registry: ToolRegistry | None = None) -> ConversationService:
    return ConversationService(
        registry=registry or build_mock_registry(),
        planner=RulePlanner(),
    )


def test_encode_sse_uses_named_event_id_and_compact_json() -> None:
    frame = encode_sse(
        AgentEvent(sequence=3, type="planning.started", data={"语言": "中文"})
    )

    assert frame.startswith("id: 3\nevent: planning.started\ndata: ")
    assert '"语言":"中文"' in frame
    assert frame.endswith("\n\n")


def test_stream_emits_agent_lifecycle_in_order_and_finishes_with_response() -> None:
    events = parse_frames(
        list(
            stream_conversation(
                build_service(),
                ChatRequest(text="大阪天气怎么样", location="大阪"),
            )
        )
    )

    event_types = [event["type"] for event in events]
    assert event_types == [
        "request.accepted",
        "planning.started",
        "planning.completed",
        "tool.started",
        "tool.completed",
        "verification.completed",
        "response.completed",
    ]
    assert [event["sequence"] for event in events] == list(
        range(1, len(events) + 1)
    )
    final_response = events[-1]["data"]["response"]
    assert "当前天气" in final_response["answer"]
    assert final_response["trace"]["executions"][0]["name"] == "get_weather"


def test_stream_exposes_memory_recall_without_replaying_chat_history() -> None:
    service = build_service()
    service.chat(
        ChatRequest(
            text="记住位置",
            session_id="stream-memory",
            location="京都站",
            preferences=["素食"],
        )
    )

    events = parse_frames(
        list(
            stream_conversation(
                service,
                ChatRequest(text="附近找一家餐厅", session_id="stream-memory"),
            )
        )
    )
    recalled = next(event for event in events if event["type"] == "memory.recalled")

    assert recalled["data"]["fields"] == ["location", "preferences"]
    assert "history" not in recalled["data"]


def test_booking_stream_waits_for_confirmation_without_tool_execution() -> None:
    events = parse_frames(
        list(
            stream_conversation(
                build_service(),
                ChatRequest(
                    text="帮我预约晚餐",
                    session_id="stream-booking",
                    location="大阪",
                ),
            )
        )
    )
    event_types = [event["type"] for event in events]

    assert "confirmation.awaiting" in event_types
    assert "tool.started" not in event_types
    confirmation = next(
        event for event in events if event["type"] == "confirmation.awaiting"
    )
    assert len(confirmation["data"]["action_id"]) == 32
    final_response = events[-1]["data"]["response"]
    assert final_response["trace"]["confirmation_status"] == "awaiting"


def test_stream_reports_bounded_recovery_for_tool_failure() -> None:
    class FailingWeatherTool:
        name = "get_weather"
        description = "Always fail for stream recovery testing."

        def invoke(self, arguments: dict[str, object]) -> dict[str, object]:
            raise RuntimeError("weather unavailable")

    registry = ToolRegistry(
        [
            MockPoiSearchTool(),
            FailingWeatherTool(),
            MockTranslateTool(),
            MockTravelKnowledgeTool(),
        ]
    )
    events = parse_frames(
        list(
            stream_conversation(
                build_service(registry),
                ChatRequest(text="东京天气怎么样", location="东京"),
            )
        )
    )
    event_types = [event["type"] for event in events]

    assert event_types.count("tool.started") == 2
    assert event_types.count("tool.completed") == 2
    assert event_types.count("verification.completed") == 2
    assert event_types.count("recovery.started") == 1
    assert events[-1]["type"] == "response.completed"
    assert "没有编造结果" in events[-1]["data"]["response"]["answer"]
