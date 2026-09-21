from fastapi import FastAPI

from travel_agent.graph import run_agent
from travel_agent.models import AgentResponse, TravelRequest
from travel_agent.planner import build_planner_from_env
from travel_agent.tools import build_tool_registry_from_env

planner = build_planner_from_env()
tool_registry = build_tool_registry_from_env()

app = FastAPI(
    title="Location-Aware Travel Agent",
    version="0.1.0",
    description="Auditable travel-agent vertical slice with replaceable tool providers.",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "provider": tool_registry.provider}


@app.post("/v1/chat", response_model=AgentResponse)
def chat(request: TravelRequest) -> AgentResponse:
    return run_agent(request, registry=tool_registry, planner=planner)
