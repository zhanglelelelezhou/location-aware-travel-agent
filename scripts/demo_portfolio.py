from __future__ import annotations

import json
from typing import Any

from travel_agent.models import ChatRequest, ConfirmationRequest
from travel_agent.planner import RulePlanner
from travel_agent.session import ConversationService
from travel_agent.streaming import stream_conversation
from travel_agent.tools import build_mock_registry


def show(title: str, payload: dict[str, Any]) -> None:
    print(f"\n=== {title} ===")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def response_summary(response: Any) -> dict[str, Any]:
    return {
        "answer": response.answer,
        "intents": response.trace.intents,
        "tools": [call.name for call in response.trace.plan],
        "memory_recalled": response.trace.memory_recalled,
        "needs_confirmation": response.trace.needs_confirmation,
        "confirmation_status": response.trace.confirmation_status,
        "retry_count": response.trace.retry_count,
    }


def parse_event_type(frame: str) -> str:
    return next(
        line.removeprefix("event: ")
        for line in frame.splitlines()
        if line.startswith("event: ")
    )


def main() -> None:
    service = ConversationService(
        registry=build_mock_registry(),
        planner=RulePlanner(),
    )

    composite = service.chat(
        ChatRequest(
            text="大阪站附近找一家素食餐厅，并生成一句日语询问语",
            location="大阪站",
            preferences=["素食"],
        )
    )
    assert [call.name for call in composite.trace.plan] == [
        "search_poi",
        "translate_phrase",
    ]
    show("1. 复合请求：规划并调用两个工具", response_summary(composite))

    session_id = "portfolio-demo"
    service.chat(
        ChatRequest(
            text="记住我的位置和偏好",
            session_id=session_id,
            location="大阪站",
            preferences=["素食"],
        )
    )
    recalled = service.chat(
        ChatRequest(text="附近找一家餐厅", session_id=session_id)
    )
    assert set(recalled.trace.memory_recalled) == {"location", "preferences"}
    show("2. 有界记忆：只召回结构化事实", response_summary(recalled))

    pending = service.chat(
        ChatRequest(
            text="帮我预约今晚七点的餐位",
            session_id=session_id,
        )
    )
    action_id = pending.trace.pending_action_id
    assert action_id is not None
    assert pending.trace.executions == []
    approved = service.confirm(
        session_id,
        ConfirmationRequest(action_id=action_id, decision="approve"),
    )
    replay = service.confirm(
        session_id,
        ConfirmationRequest(action_id=action_id, decision="approve"),
    )
    show(
        "3. 人工确认：批准前零执行，令牌不可重放",
        {
            "before_confirmation": pending.trace.confirmation_status,
            "executions_before_confirmation": len(pending.trace.executions),
            "after_confirmation": approved.trace.confirmation_status,
            "external_request_sent": approved.trace.confirmation_result[
                "external_request_sent"
            ],
            "replay": replay.trace.confirmation_status,
        },
    )

    frames = list(
        stream_conversation(
            service,
            ChatRequest(text="帮我安排大阪半日行程", location="大阪"),
        )
    )
    event_types = [parse_event_type(frame) for frame in frames if not frame.startswith(":")]
    assert event_types[-1] == "response.completed"
    show("4. SSE：真实 Agent 生命周期事件", {"events": event_types})

    print("\nDemo completed: all offline safety and lifecycle assertions passed.")


if __name__ == "__main__":
    main()
