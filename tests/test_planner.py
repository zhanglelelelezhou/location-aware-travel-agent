from __future__ import annotations

from typing import Any

import httpx

from travel_agent.models import TravelRequest
from travel_agent.planner import (
    LLMPlanner,
    OpenAICompatibleProvider,
    ProviderResult,
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
    assert [call.name for call in result.decision.tool_calls] == [
        "search_poi",
        "translate_phrase",
    ]


def test_openai_compatible_provider_parses_usage_and_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer test-key"
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
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = provider.generate_json(system_prompt="plan", user_payload={"text": "hello"})

    assert result.payload["intents"] == ["general"]
    assert result.prompt_tokens == 12
    assert result.completion_tokens == 7
