from __future__ import annotations

from pydantic import BaseModel, Field

from travel_agent.models import PlannedToolCall, PlanningDecision, TravelRequest


class PolicyOutcome(BaseModel):
    decision: PlanningDecision
    adjustments: list[str] = Field(default_factory=list)


def enforce_travel_policy(
    decision: PlanningDecision, request: TravelRequest
) -> PolicyOutcome:
    """Enforce deterministic product invariants after semantic planning."""

    adjustments: list[str] = []
    missing_fields = list(decision.missing_fields)
    tool_calls = list(decision.tool_calls)
    needs_confirmation = decision.needs_confirmation

    if request.location and "location" in missing_fields:
        missing_fields.remove("location")
        adjustments.append("input:clear_resolved_location")

    if "booking" in decision.intents:
        if not needs_confirmation:
            needs_confirmation = True
            adjustments.append("booking:require_confirmation")
        if tool_calls:
            tool_calls = []
            adjustments.append("booking:block_tool_execution")

    if "itinerary" in decision.intents and not request.location:
        if "location" not in missing_fields:
            missing_fields.append("location")
            adjustments.append("itinerary:require_location")
        if tool_calls:
            tool_calls = []
            adjustments.append("missing_input:block_tool_execution")

    if (
        "itinerary" in decision.intents
        and "booking" not in decision.intents
        and request.location
        and not missing_fields
    ):
        names = {call.name for call in tool_calls}
        if "search_poi" not in names:
            tool_calls.append(
                PlannedToolCall(
                    name="search_poi",
                    arguments={
                        "location": request.location,
                        "preferences": request.preferences,
                    },
                )
            )
            adjustments.append("itinerary:add_search_poi")
        if "get_weather" not in names:
            tool_calls.append(
                PlannedToolCall(
                    name="get_weather", arguments={"location": request.location}
                )
            )
            adjustments.append("itinerary:add_get_weather")

    revised = PlanningDecision.model_validate(
        {
            "intents": decision.intents,
            "missing_fields": missing_fields,
            "tool_calls": tool_calls,
            "needs_confirmation": needs_confirmation,
        }
    )
    return PolicyOutcome(decision=revised, adjustments=adjustments)
