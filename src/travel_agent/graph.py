from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from travel_agent.models import (
    AgentResponse,
    AgentTrace,
    Intent,
    PlannedToolCall,
    ToolExecution,
    TravelRequest,
)
from travel_agent.tools import ToolRegistry, build_mock_registry


class AgentState(TypedDict, total=False):
    request: TravelRequest
    intents: list[Intent]
    plan: list[PlannedToolCall]
    executions: list[ToolExecution]
    retry_count: int
    error: str | None
    answer: str
    response: AgentResponse


def _detect_intents(text: str) -> list[Intent]:
    normalized = text.lower()
    detected: list[Intent] = []
    keyword_groups: list[tuple[Intent, tuple[str, ...]]] = [
        ("dining", ("餐厅", "吃", "点餐", "素食", "restaurant", "food")),
        ("itinerary", ("行程", "景点", "安排", "路线", "itinerary")),
        ("translation", ("翻译", "日语", "怎么说", "translate")),
        ("safety", ("过敏", "禁忌", "风险", "allergy", "safe")),
    ]
    for intent, keywords in keyword_groups:
        if any(keyword in normalized for keyword in keywords):
            detected.append(intent)
    return detected or ["general"]


def _understand(state: AgentState) -> dict[str, Any]:
    return {"intents": _detect_intents(state["request"].text), "retry_count": 0}


def _plan(state: AgentState) -> dict[str, Any]:
    request = state["request"]
    calls: list[PlannedToolCall] = []
    common = {"location": request.location, "preferences": request.preferences}
    if "dining" in state["intents"] or "itinerary" in state["intents"]:
        calls.append(PlannedToolCall(name="search_poi", arguments=common))
    if "itinerary" in state["intents"]:
        calls.append(PlannedToolCall(name="get_weather", arguments={"location": request.location}))
    if "safety" in state["intents"]:
        calls.append(
            PlannedToolCall(
                name="search_travel_knowledge", arguments={"query": request.text}
            )
        )
    if "translation" in state["intents"] or "dining" in state["intents"]:
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
    return {"plan": calls}


def _execute_with(registry: ToolRegistry):
    def execute(state: AgentState) -> dict[str, Any]:
        executions: list[ToolExecution] = []
        first_error: str | None = None
        for call in state.get("plan", []):
            try:
                output = registry.invoke(call.name, call.arguments)
                executions.append(
                    ToolExecution(name=call.name, arguments=call.arguments, output=output)
                )
            # Tool adapters cross process/network boundaries and can raise provider-specific
            # exceptions. This boundary normalizes them into an auditable execution result.
            except Exception as exc:  # noqa: BLE001
                first_error = f"{call.name}: {exc}"
                executions.append(
                    ToolExecution(name=call.name, arguments=call.arguments, error=str(exc))
                )
        return {"executions": executions, "error": first_error}

    return execute


def _verify(state: AgentState) -> dict[str, Any]:
    if not state.get("plan"):
        return {"error": None}
    failed = [item.name for item in state.get("executions", []) if item.error]
    if failed:
        return {"error": state.get("error") or f"Tools failed: {', '.join(failed)}"}
    return {"error": None}


def _route_after_verify(state: AgentState) -> str:
    if state.get("error") and state.get("retry_count", 0) < 1:
        return "recover"
    return "respond"


def _recover(state: AgentState) -> dict[str, Any]:
    return {"retry_count": state.get("retry_count", 0) + 1, "error": None}


def _respond(state: AgentState) -> dict[str, Any]:
    if state.get("error"):
        answer = "工具暂时不可用，我没有编造结果。请稍后重试或换一个条件。"
    else:
        parts: list[str] = []
        for execution in state.get("executions", []):
            output = execution.output or {}
            if execution.name == "search_poi" and output.get("results"):
                poi = output["results"][0]
                parts.append(
                    f"推荐 {poi['name']}，从{output['location']}步行约{poi['walking_minutes']}分钟。"
                )
            elif execution.name == "get_weather":
                parts.append(
                    f"当前天气为 {output['condition']}，约 {output['temperature_c']}°C，建议准备雨具。"
                )
            elif execution.name == "translate_phrase":
                parts.append(f"可向店员询问：{output['translated_text']}")
            elif execution.name == "search_travel_knowledge" and output.get("passages"):
                parts.append(output["passages"][0]["text"])
        answer = " ".join(parts) or "我已理解请求，但当前 Mock 工具还不支持这个场景。"

    response = AgentResponse(
        answer=answer,
        trace=AgentTrace(
            intents=state.get("intents", ["general"]),
            plan=state.get("plan", []),
            executions=state.get("executions", []),
            retry_count=state.get("retry_count", 0),
        ),
    )
    return {"answer": answer, "response": response}


def build_agent(registry: ToolRegistry | None = None):
    registry = registry or build_mock_registry()
    workflow = StateGraph(AgentState)
    workflow.add_node("understand", _understand)
    workflow.add_node("plan", _plan)
    workflow.add_node("execute", _execute_with(registry))
    workflow.add_node("verify", _verify)
    workflow.add_node("recover", _recover)
    workflow.add_node("respond", _respond)

    workflow.add_edge(START, "understand")
    workflow.add_edge("understand", "plan")
    workflow.add_edge("plan", "execute")
    workflow.add_edge("execute", "verify")
    workflow.add_conditional_edges(
        "verify", _route_after_verify, {"recover": "recover", "respond": "respond"}
    )
    workflow.add_edge("recover", "execute")
    workflow.add_edge("respond", END)
    return workflow.compile()


def run_agent(request: TravelRequest, registry: ToolRegistry | None = None) -> AgentResponse:
    result = build_agent(registry).invoke({"request": request})
    return result["response"]
