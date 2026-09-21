from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Intent = Literal["dining", "itinerary", "translation", "safety", "general"]


class TravelRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2_000)
    location: str | None = None
    target_language: str = "ja"
    preferences: list[str] = Field(default_factory=list)
    user_id: str = "demo-user"


class PlannedToolCall(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


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


class AgentResponse(BaseModel):
    answer: str
    trace: AgentTrace

