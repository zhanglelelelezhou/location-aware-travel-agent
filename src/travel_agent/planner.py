from __future__ import annotations

import json
import os
import time
from typing import Any, Literal, Protocol, cast

import httpx
from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

from travel_agent.models import Intent, PlannedToolCall, PlanningDecision, TravelRequest

ALLOWED_TOOLS = {
    "search_poi",
    "get_weather",
    "translate_phrase",
    "search_travel_knowledge",
}


class PlannerResult(BaseModel):
    decision: PlanningDecision
    planner_used: Literal["rule", "llm", "rule_fallback"]
    repaired: bool = False
    error: str | None = None
    latency_ms: int = 0
    model: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class Planner(Protocol):
    def plan(self, request: TravelRequest) -> PlannerResult: ...


class ProviderResult(BaseModel):
    payload: dict[str, Any]
    latency_ms: int = 0
    model: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class JsonProvider(Protocol):
    def generate_json(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, Any],
        repair_context: str | None = None,
    ) -> ProviderResult: ...


def detect_intents(text: str) -> list[Intent]:
    normalized = text.lower()
    detected: list[Intent] = []
    keyword_groups: list[tuple[Intent, tuple[str, ...]]] = [
        (
            "dining",
            ("餐厅", "吃", "点餐", "餐位", "素食", "restaurant", "food", "dish", "table"),
        ),
        ("itinerary", ("行程", "景点", "安排", "路线", "itinerary")),
        ("translation", ("翻译", "日语", "怎么说", "translate")),
        ("safety", ("过敏", "禁忌", "风险", "allergy", "safe")),
        ("weather", ("天气", "气温", "weather")),
        ("booking", ("预订", "预约", "book", "reserve")),
    ]
    for intent, keywords in keyword_groups:
        if any(keyword in normalized for keyword in keywords):
            detected.append(intent)
    return detected or ["general"]


def build_rule_decision(request: TravelRequest) -> PlanningDecision:
    intents = detect_intents(request.text)
    calls: list[PlannedToolCall] = []
    common = {"location": request.location, "preferences": request.preferences}
    normalized = request.text.lower()
    venue_discovery = any(
        keyword in normalized for keyword in ("餐厅", "附近", "周围", "restaurant", "nearby", "店")
    )
    if "booking" not in intents:
        if ("dining" in intents and venue_discovery) or "itinerary" in intents:
            calls.append(PlannedToolCall(name="search_poi", arguments=common))
        if "itinerary" in intents or "weather" in intents:
            calls.append(
                PlannedToolCall(name="get_weather", arguments={"location": request.location})
            )
        if "safety" in intents:
            calls.append(
                PlannedToolCall(
                    name="search_travel_knowledge", arguments={"query": request.text}
                )
            )
        if "translation" in intents:
            calls.append(
                PlannedToolCall(
                    name="translate_phrase",
                    arguments={
                        "text": request.text,
                        "target_language": request.target_language,
                        "preferences": request.preferences,
                    },
                )
            )

    location_tools = {"search_poi", "get_weather"}
    missing_fields = (
        ["location"]
        if not request.location and any(call.name in location_tools for call in calls)
        else []
    )
    if missing_fields:
        calls = []
    return PlanningDecision(
        intents=intents,
        missing_fields=missing_fields,
        tool_calls=calls,
        needs_confirmation="booking" in intents,
    )


class RulePlanner:
    def plan(self, request: TravelRequest) -> PlannerResult:
        return PlannerResult(decision=build_rule_decision(request), planner_used="rule")


class OpenAICompatibleProvider:
    """Minimal provider for OpenAI-compatible chat-completions APIs."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 20.0,
        json_mode: bool = True,
        thinking_mode: Literal["enabled", "disabled"] | None = None,
        max_tokens: int = 1500,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.json_mode = json_mode
        self.thinking_mode = thinking_mode
        self.max_tokens = max_tokens
        self.client = client or httpx.Client(timeout=timeout_seconds)

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, Any],
        repair_context: str | None = None,
    ) -> ProviderResult:
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": json.dumps(user_payload, ensure_ascii=False),
            },
        ]
        if repair_context:
            messages.append({"role": "user", "content": repair_context})

        started = time.perf_counter()
        request_body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": self.max_tokens,
        }
        if self.json_mode:
            request_body["response_format"] = {"type": "json_object"}
        if self.thinking_mode:
            request_body["thinking"] = {"type": self.thinking_mode}
        response = self.client.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=request_body,
        )
        response.raise_for_status()
        body = response.json()
        content = body["choices"][0]["message"]["content"]
        payload = _parse_json_content(content)
        usage = body.get("usage") or {}
        return ProviderResult(
            payload=payload,
            latency_ms=round((time.perf_counter() - started) * 1000),
            model=body.get("model") or self.model,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
        )


def _parse_json_content(content: str | dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(content, dict):
        return content
    if not content or not content.strip():
        raise ValueError("Planner returned empty content.")
    stripped = content.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        stripped = "\n".join(lines[1:-1]).strip()
    parsed = json.loads(stripped)
    if not isinstance(parsed, dict):
        raise TypeError("Planner response must be a JSON object.")
    return parsed


def _system_prompt() -> str:
    schema = json.dumps(PlanningDecision.model_json_schema(), ensure_ascii=False)
    example = {
        "intents": ["weather"],
        "missing_fields": [],
        "tool_calls": [
            {"name": "get_weather", "arguments": {"location": "Tokyo"}}
        ],
        "needs_confirmation": False,
    }
    return (
        "You are the planner for a location-aware travel agent. "
        "Return one JSON object only, matching the supplied JSON schema. "
        "Follow this policy exactly: search_poi is for explicit venue or attraction "
        "discovery; get_weather is required for weather questions and itinerary planning; "
        "translate_phrase is used only when translation or phrase generation is explicitly "
        "requested; search_travel_knowledge is required for allergy or travel-safety advice. "
        "Greetings and unsupported currency conversion are general intent with no tools. "
        "If a required location or translation source text is missing, use only the canonical "
        "field name location or text in missing_fields and return no tool calls. "
        "needs_confirmation is only for side-effect "
        "requests such as booking or payment. Booking requests must set it true and must not "
        "create an unsupported tool call. Use each tool at most once. Never invent a tool. "
        f"Example JSON output: {json.dumps(example, ensure_ascii=False)}. "
        f"JSON schema: {schema}"
    )


def _validate_decision(payload: dict[str, Any]) -> PlanningDecision:
    decision = PlanningDecision.model_validate(payload)
    unknown = [call.name for call in decision.tool_calls if call.name not in ALLOWED_TOOLS]
    if unknown:
        raise ValueError(f"Unknown tools: {', '.join(unknown)}")
    return decision


class LLMPlanner:
    def __init__(self, provider: JsonProvider, fallback: Planner | None = None) -> None:
        self.provider = provider
        self.fallback = fallback or RulePlanner()

    def plan(self, request: TravelRequest) -> PlannerResult:
        user_payload = request.model_dump()
        previous_payload: dict[str, Any] | None = None
        last_error: str | None = None
        total_latency = 0
        prompt_tokens = 0
        completion_tokens = 0
        model: str | None = None

        for attempt in range(2):
            repair_context = None
            if attempt:
                repair_context = (
                    "The previous JSON failed validation. Correct it and return JSON only. "
                    f"Validation error: {last_error}. Previous JSON: "
                    f"{json.dumps(previous_payload, ensure_ascii=False)}"
                )
            try:
                provider_result = self.provider.generate_json(
                    system_prompt=_system_prompt(),
                    user_payload=user_payload,
                    repair_context=repair_context,
                )
                previous_payload = provider_result.payload
                total_latency += provider_result.latency_ms
                model = provider_result.model or model
                prompt_tokens += provider_result.prompt_tokens or 0
                completion_tokens += provider_result.completion_tokens or 0
                decision = _validate_decision(provider_result.payload)
                return PlannerResult(
                    decision=decision,
                    planner_used="llm",
                    repaired=attempt == 1,
                    latency_ms=total_latency,
                    model=model,
                    prompt_tokens=prompt_tokens or None,
                    completion_tokens=completion_tokens or None,
                )
            except (
                ValidationError,
                TypeError,
                ValueError,
                KeyError,
                IndexError,
                json.JSONDecodeError,
            ) as exc:
                last_error = str(exc)
            except httpx.HTTPError as exc:
                last_error = f"Provider request failed: {exc}"
                break

        fallback_result = self.fallback.plan(request)
        return fallback_result.model_copy(
            update={
                "planner_used": "rule_fallback",
                "repaired": previous_payload is not None,
                "error": last_error,
                "latency_ms": total_latency,
                "model": model,
                "prompt_tokens": prompt_tokens or None,
                "completion_tokens": completion_tokens or None,
            }
        )


def build_planner_from_env(kind: str | None = None) -> Planner:
    load_dotenv()
    selected = (kind or os.getenv("AGENT_PLANNER", "rule")).lower()
    if selected == "rule":
        return RulePlanner()
    if selected != "llm":
        raise ValueError(f"Unsupported planner: {selected}")

    required = {
        "LLM_BASE_URL": os.getenv("LLM_BASE_URL"),
        "LLM_API_KEY": os.getenv("LLM_API_KEY"),
        "LLM_MODEL": os.getenv("LLM_MODEL"),
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise ValueError(f"Missing LLM settings: {', '.join(missing)}")
    provider = OpenAICompatibleProvider(
        base_url=required["LLM_BASE_URL"] or "",
        api_key=required["LLM_API_KEY"] or "",
        model=required["LLM_MODEL"] or "",
        json_mode=os.getenv("LLM_JSON_MODE", "true").lower() not in {"0", "false", "no"},
        thinking_mode=_thinking_mode_from_env(required["LLM_BASE_URL"] or ""),
        max_tokens=int(os.getenv("LLM_MAX_TOKENS", "1500")),
    )
    return LLMPlanner(provider)


def _thinking_mode_from_env(base_url: str) -> Literal["enabled", "disabled"] | None:
    configured = os.getenv("LLM_THINKING_MODE")
    if configured:
        normalized = configured.lower()
        if normalized not in {"enabled", "disabled"}:
            raise ValueError("LLM_THINKING_MODE must be enabled or disabled")
        return cast(Literal["enabled", "disabled"], normalized)
    if "api.deepseek.com" in base_url.lower():
        return "disabled"
    return None
