from typing import Annotated

from fastapi import FastAPI, Path
from fastapi.responses import StreamingResponse

from travel_agent.models import AgentResponse, ChatRequest, ConfirmationRequest
from travel_agent.planner import build_planner_from_env
from travel_agent.session import ConversationService, build_session_store_from_env
from travel_agent.streaming import stream_conversation
from travel_agent.tools import build_tool_registry_from_env

planner = build_planner_from_env()
tool_registry = build_tool_registry_from_env()
conversation_service = ConversationService(
    registry=tool_registry,
    planner=planner,
    store=build_session_store_from_env(),
)
SessionId = Annotated[
    str,
    Path(
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    ),
]

app = FastAPI(
    title="Location-Aware Travel Agent",
    version="0.1.0",
    description="Auditable travel-agent vertical slice with replaceable tool providers.",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "provider": tool_registry.provider}


@app.post("/v1/chat", response_model=AgentResponse)
def chat(request: ChatRequest) -> AgentResponse:
    return conversation_service.chat(request)


@app.post("/v1/chat/stream")
def chat_stream(request: ChatRequest) -> StreamingResponse:
    return StreamingResponse(
        stream_conversation(conversation_service, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post(
    "/v1/sessions/{session_id}/confirm",
    response_model=AgentResponse,
)
def confirm(session_id: SessionId, request: ConfirmationRequest) -> AgentResponse:
    return conversation_service.confirm(session_id, request)


@app.delete("/v1/sessions/{session_id}")
def clear_session(session_id: SessionId) -> dict[str, bool]:
    return {"cleared": conversation_service.clear(session_id)}
