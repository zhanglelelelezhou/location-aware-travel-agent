from __future__ import annotations

import json
from typing import Any

import httpx

from travel_agent.models import TravelRequest
from travel_agent.planner import (
    LLMPlanner,
    OpenAICompatibleProvider,
    ProviderResult,
    detect_intents,
)


class SequenceProvider:
    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        self.payloads = payloads
        self.calls = 0
        self.repair_contexts: list[str | None] = []

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, Any],
        repair_context: str | None = None,
    ) -> ProviderResult:
        assert "search_poi" in system_prompt
        assert user_payload["text"]
        self.repair_contexts.append(repair_context)
        payload = self.payloads[min(self.calls, len(self.payloads) - 1)]
        self.calls += 1
        return ProviderResult(
            payload=payload,
            latency_ms=5,
            prompt_tokens=10,
            completion_tokens=4,
        )


def test_rule_intent_disambiguation_uses_dominant_user_action() -> None:
    assert detect_intents("我对花生严重过敏，点餐时要注意什么") == ["safety"]
    assert detect_intents("帮我预约今晚七点的餐位") == ["booking"]
    assert detect_intents("Book a table for two tonight") == ["booking"]


def test_safety_and_dining_remain_distinct_for_venue_discovery() -> None:
    assert detect_intents("推荐适合花生过敏者的餐厅") == ["dining", "safety"]


def test_llm_planner_accepts_valid_structured_plan() -> None:
    provider = SequenceProvider(
        [
            {
                "intents": ["dining"],
                "missing_fields": [],
                "tool_calls": [
                    {"name": "search_poi", "arguments": {"location": "难波"}}
                ],
                "needs_confirmation": False,
            }
        ]
    )

    result = LLMPlanner(provider).plan(TravelRequest(text="肚子饿了", location="难波"))

    assert result.planner_used == "llm"
    assert result.decision.intents == ["dining"]
    assert result.prompt_tokens == 10
    assert not result.repaired


def test_llm_planner_repairs_invalid_tool_once() -> None:
    provider = SequenceProvider(
        [
            {
                "intents": ["dining"],
                "missing_fields": [],
                "tool_calls": [{"name": "invented_tool", "arguments": {}}],
                "needs_confirmation": False,
            },
            {
                "intents": ["dining"],
                "missing_fields": [],
                "tool_calls": [{"name": "search_poi", "arguments": {}}],
                "needs_confirmation": False,
            },
        ]
    )

    result = LLMPlanner(provider).plan(TravelRequest(text="找一家店", location="大阪"))

    assert result.planner_used == "llm"
    assert result.repaired
    assert provider.calls == 2
    assert provider.repair_contexts[1] is not None


def test_llm_planner_falls_back_after_two_invalid_outputs() -> None:
    provider = SequenceProvider([{"invalid": True}, {"still_invalid": True}])

    result = LLMPlanner(provider).plan(
        TravelRequest(text="找一家素食餐厅", location="大阪", preferences=["素食"])
    )

    assert result.planner_used == "rule_fallback"
    assert result.error
    assert [call.name for call in result.decision.tool_calls] == ["search_poi"]


def test_openai_compatible_provider_parses_usage_and_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer test-key"
        request_body = json.loads(request.content)
        assert request_body["thinking"] == {"type": "disabled"}
        assert request_body["max_tokens"] == 900
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"intents":["general"],"missing_fields":[],"tool_calls":[],"needs_confirmation":false}'
                        }
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 7},
            },
        )

    provider = OpenAICompatibleProvider(
        base_url="https://example.test/v1",
        api_key="test-key",
        model="test-model",
        thinking_mode="disabled",
        max_tokens=900,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = provider.generate_json(system_prompt="plan", user_payload={"text": "hello"})

    assert result.payload["intents"] == ["general"]
    assert result.prompt_tokens == 12
    assert result.completion_tokens == 7


def test_llm_planner_retries_empty_content_error() -> None:
    class EmptyThenValidProvider:
        def __init__(self) -> None:
            self.calls = 0

        def generate_json(self, **_: object) -> ProviderResult:
            self.calls += 1
            if self.calls == 1:
                raise ValueError("Planner returned empty content.")
            return ProviderResult(
                payload={
                    "intents": ["general"],
                    "missing_fields": [],
                    "tool_calls": [],
                    "needs_confirmation": False,
                },
                model="deepseek-flash",
            )

    provider = EmptyThenValidProvider()
    result = LLMPlanner(provider).plan(TravelRequest(text="你好"))

    assert provider.calls == 2
    assert result.repaired
    assert result.model == "deepseek-flash"


def test_policy_completes_itinerary_tool_plan_and_records_adjustment() -> None:
    provider = SequenceProvider(
        [
            {
                "intents": ["itinerary"],
                "missing_fields": [],
                "tool_calls": [
                    {"name": "get_weather", "arguments": {"location": "京都"}}
                ],
                "needs_confirmation": False,
            }
        ]
    )

    result = LLMPlanner(provider).plan(
        TravelRequest(text="安排京都半日游", location="京都")
    )

    assert {call.name for call in result.decision.tool_calls} == {
        "search_poi",
        "get_weather",
    }
    assert result.policy_adjustments == ["itinerary:add_search_poi"]


def test_policy_requires_location_before_itinerary_tools() -> None:
    provider = SequenceProvider(
        [
            {
                "intents": ["itinerary"],
                "missing_fields": [],
                "tool_calls": [],
                "needs_confirmation": False,
            }
        ]
    )

    result = LLMPlanner(provider).plan(TravelRequest(text="帮我安排半日游"))

    assert result.decision.missing_fields == ["location"]
    assert result.decision.tool_calls == []
    assert result.policy_adjustments == ["itinerary:require_location"]


def test_policy_blocks_tool_execution_while_booking_awaits_confirmation() -> None:
    provider = SequenceProvider(
        [
            {
                "intents": ["booking"],
                "missing_fields": [],
                "tool_calls": [
                    {"name": "search_poi", "arguments": {"location": "大阪"}}
                ],
                "needs_confirmation": True,
            }
        ]
    )

    result = LLMPlanner(provider).plan(
        TravelRequest(text="帮我预约大阪的晚餐", location="大阪")
    )

    assert result.decision.tool_calls == []
    assert result.decision.needs_confirmation
    assert result.policy_adjustments == ["booking:block_tool_execution"]


def test_policy_rejects_llm_hallucinated_coordinates() -> None:
    provider = SequenceProvider(
        [
            {
                "intents": ["weather"],
                "missing_fields": [],
                "tool_calls": [
                    {
                        "name": "get_weather",
                        "arguments": {
                            "location": "错误地点",
                            "latitude": 0,
                            "longitude": 0,
                        },
                    }
                ],
                "needs_confirmation": False,
            }
        ]
    )

    result = LLMPlanner(provider).plan(
        TravelRequest(text="东京天气如何", location="东京")
    )
    arguments = result.decision.tool_calls[0].arguments

    assert arguments == {"location": "东京"}
    assert result.policy_adjustments == [
        "location:normalize_name",
        "location:remove_untrusted_coordinates",
    ]
