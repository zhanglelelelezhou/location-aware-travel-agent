from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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

    @model_validator(mode="after")
    def validate_execution_safety(self) -> PlanningDecision:
        unknown_missing = set(self.missing_fields) - {"location", "text"}
        if unknown_missing:
            raise ValueError("missing_fields may contain only location or text")
        if self.missing_fields and self.tool_calls:
            raise ValueError("tool_calls must be empty while required fields are missing")
        if "booking" in self.intents and not self.needs_confirmation:
            raise ValueError("booking requests require explicit confirmation")
        names = [call.name for call in self.tool_calls]
        if len(names) != len(set(names)):
            raise ValueError("duplicate tool calls are not allowed")
        return self


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
    planner_model: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    policy_adjustments: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    needs_confirmation: bool = False


class AgentResponse(BaseModel):
    answer: str
    trace: AgentTrace
