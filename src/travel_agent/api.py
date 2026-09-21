from fastapi import FastAPI

from travel_agent.graph import run_agent
from travel_agent.models import AgentResponse, TravelRequest

app = FastAPI(
    title="Location-Aware Travel Agent",
    version="0.1.0",
    description="Auditable travel-agent vertical slice with deterministic mock tools.",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "provider": "mock"}


@app.post("/v1/chat", response_model=AgentResponse)
def chat(request: TravelRequest) -> AgentResponse:
    return run_agent(request)

