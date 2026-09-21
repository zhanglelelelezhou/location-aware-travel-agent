from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Intent = Literal[
    "dining",
    "itinerary",
    "translation",
    "safety",
    "weather",
    "booking",
    "general",
]


class TravelRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2_000)
    location: str | None = None
    target_language: str = "ja"
    preferences: list[str] = Field(default_factory=list)
    user_id: str = "demo-user"


class PlannedToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class PlanningDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intents: list[Intent] = Field(min_length=1)
    missing_fields: list[str] = Field(default_factory=list)
    tool_calls: list[PlannedToolCall] = Field(default_factory=list)
    needs_confirmation: bool = False


class ToolExecution(BaseModel):
    name: str
    arguments: dict[str, Any]
    output: dict[str, Any] | None = None
    error: str | None = None


class AgentTrace(BaseModel):
    intents: list[Intent]
    plan: list[PlannedToolCall]
    executions: list[ToolExecution]
    retry_count: int = 0
    planner_used: Literal["rule", "llm", "rule_fallback"] = "rule"
    planner_repaired: bool = False
    planner_error: str | None = None
    planner_latency_ms: int = 0
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    missing_fields: list[str] = Field(default_factory=list)
    needs_confirmation: bool = False


class AgentResponse(BaseModel):
    answer: str
    trace: AgentTrace
