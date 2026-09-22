from __future__ import annotations

import json
import logging
import queue
import threading
from collections.abc import Iterator
from typing import Any

from travel_agent.models import AgentEvent, ChatRequest
from travel_agent.session import ConversationService

_STREAM_END = object()
LOGGER = logging.getLogger(__name__)


def stream_conversation(
    service: ConversationService,
    request: ChatRequest,
    *,
    keepalive_seconds: float = 15.0,
) -> Iterator[str]:
    """Run the synchronous agent in a worker and expose ordered SSE frames."""

    events: queue.Queue[AgentEvent | object] = queue.Queue()
    sequence = 0

    def emit(event_type: str, data: dict[str, Any]) -> None:
        nonlocal sequence
        sequence += 1
        events.put(AgentEvent(sequence=sequence, type=event_type, data=data))

    def worker() -> None:
        try:
            response = service.chat(request, event_sink=emit)
            emit(
                "response.completed",
                {"response": response.model_dump(mode="json")},
            )
        except Exception as exc:
            LOGGER.exception("Agent SSE worker failed")
            emit(
                "stream.error",
                {
                    "error_type": type(exc).__name__,
                    "message": "Agent stream failed before completion.",
                },
            )
        finally:
            events.put(_STREAM_END)

    threading.Thread(target=worker, daemon=True, name="travel-agent-sse").start()
    while True:
        try:
            item = events.get(timeout=keepalive_seconds)
        except queue.Empty:
            yield ": keepalive\n\n"
            continue
        if item is _STREAM_END:
            break
        if not isinstance(item, AgentEvent):
            continue
        yield encode_sse(item)


def encode_sse(event: AgentEvent) -> str:
    data = json.dumps(event.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))
    return f"id: {event.sequence}\nevent: {event.type}\ndata: {data}\n\n"


__all__ = ["encode_sse", "stream_conversation"]
