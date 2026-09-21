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

    if request.location and tool_calls:
        revised_calls: list[PlannedToolCall] = []
        normalized_name = False
        injected_coordinates = False
        removed_coordinates = False
        for call in tool_calls:
            if call.name in {"get_weather", "search_poi"}:
                arguments = dict(call.arguments)
                if arguments.get("location") != request.location:
                    arguments["location"] = request.location
                    normalized_name = True
                if request.latitude is not None and request.longitude is not None:
                    arguments["latitude"] = request.latitude
                    arguments["longitude"] = request.longitude
                    injected_coordinates = True
                else:
                    removed_latitude = arguments.pop("latitude", None)
                    removed_longitude = arguments.pop("longitude", None)
                    removed_coordinates = removed_coordinates or (
                        removed_latitude is not None or removed_longitude is not None
                    )
                revised_calls.append(call.model_copy(update={"arguments": arguments}))
            else:
                revised_calls.append(call)
        tool_calls = revised_calls
        if normalized_name:
            adjustments.append("location:normalize_name")
        if injected_coordinates:
            adjustments.append("location:inject_coordinates")
        if removed_coordinates:
            adjustments.append("location:remove_untrusted_coordinates")

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
                        "latitude": request.latitude,
                        "longitude": request.longitude,
                        "preferences": request.preferences,
                    },
                )
            )
            adjustments.append("itinerary:add_search_poi")
        if "get_weather" not in names:
            tool_calls.append(
                PlannedToolCall(
                    name="get_weather",
                    arguments={
                        "location": request.location,
                        "latitude": request.latitude,
                        "longitude": request.longitude,
                    },
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
