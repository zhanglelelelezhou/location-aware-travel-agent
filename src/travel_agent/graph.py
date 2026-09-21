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
from travel_agent.planner import Planner, RulePlanner
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
    planner_used: str
    planner_repaired: bool
    planner_error: str | None
    planner_latency_ms: int
    prompt_tokens: int | None
    completion_tokens: int | None
    missing_fields: list[str]
    needs_confirmation: bool


def _understand(state: AgentState) -> dict[str, Any]:
    return {"retry_count": 0}


def _plan_with(planner: Planner):
    def plan(state: AgentState) -> dict[str, Any]:
        result = planner.plan(state["request"])
        decision = result.decision
        return {
            "intents": decision.intents,
            "plan": decision.tool_calls,
            "missing_fields": decision.missing_fields,
            "needs_confirmation": decision.needs_confirmation,
            "planner_used": result.planner_used,
            "planner_repaired": result.repaired,
            "planner_error": result.error,
            "planner_latency_ms": result.latency_ms,
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
        }

    return plan


def _route_after_plan(state: AgentState) -> str:
    if state.get("missing_fields") or state.get("needs_confirmation"):
        return "respond"
    return "execute"


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
    if state.get("missing_fields"):
        answer = f"继续处理前还需要提供：{', '.join(state['missing_fields'])}。"
    elif state.get("needs_confirmation"):
        answer = "该请求可能产生外部操作，需要你明确确认后才能继续。"
    elif state.get("error"):
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
            planner_used=state.get("planner_used", "rule"),
            planner_repaired=state.get("planner_repaired", False),
            planner_error=state.get("planner_error"),
            planner_latency_ms=state.get("planner_latency_ms", 0),
            prompt_tokens=state.get("prompt_tokens"),
            completion_tokens=state.get("completion_tokens"),
            missing_fields=state.get("missing_fields", []),
            needs_confirmation=state.get("needs_confirmation", False),
        ),
    )
    return {"answer": answer, "response": response}


def build_agent(registry: ToolRegistry | None = None, planner: Planner | None = None):
    registry = registry or build_mock_registry()
    planner = planner or RulePlanner()
    workflow = StateGraph(AgentState)
    workflow.add_node("understand", _understand)
    workflow.add_node("plan", _plan_with(planner))
    workflow.add_node("execute", _execute_with(registry))
    workflow.add_node("verify", _verify)
    workflow.add_node("recover", _recover)
    workflow.add_node("respond", _respond)

    workflow.add_edge(START, "understand")
    workflow.add_edge("understand", "plan")
    workflow.add_conditional_edges(
        "plan", _route_after_plan, {"execute": "execute", "respond": "respond"}
    )
    workflow.add_edge("execute", "verify")
    workflow.add_conditional_edges(
        "verify", _route_after_verify, {"recover": "recover", "respond": "respond"}
    )
    workflow.add_edge("recover", "execute")
    workflow.add_edge("respond", END)
    return workflow.compile()


def run_agent(
    request: TravelRequest,
    registry: ToolRegistry | None = None,
    planner: Planner | None = None,
) -> AgentResponse:
    result = build_agent(registry, planner).invoke({"request": request})
    return result["response"]
