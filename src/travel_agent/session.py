from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import uuid4

from travel_agent.graph import run_agent
from travel_agent.models import (
    AgentResponse,
    AgentTrace,
    ChatRequest,
    ConfirmationRequest,
    PlannedToolCall,
    ToolExecution,
    TravelRequest,
)
from travel_agent.planner import Planner
from travel_agent.tools.base import ToolRegistry


@dataclass
class SessionMemory:
    location: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    preferences: list[str] = field(default_factory=list)
    turn_count: int = 0


@dataclass
class PendingAction:
    id: str
    kind: str
    summary: str
    request: TravelRequest
    created_at: float


@dataclass
class SessionRecord:
    memory: SessionMemory = field(default_factory=SessionMemory)
    pending_action: PendingAction | None = None
    updated_at: float = 0.0


class BookingGateway(Protocol):
    def submit(self, action: PendingAction) -> dict[str, Any]: ...


class DryRunBookingGateway:
    """Reproducible default: exercises the approval boundary without external writes."""

    def submit(self, action: PendingAction) -> dict[str, Any]:
        return {
            "status": "simulated",
            "provider": "dry-run",
            "external_request_sent": False,
            "action_id": action.id,
            "summary": action.summary,
        }


class InMemorySessionStore:
    """Bounded, TTL-based store for high-signal facts and one pending action."""

    def __init__(
        self,
        *,
        max_sessions: int = 1_000,
        session_ttl_seconds: float = 30 * 60,
        pending_ttl_seconds: float = 15 * 60,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_sessions < 1:
            raise ValueError("max_sessions must be positive")
        if session_ttl_seconds <= 0 or pending_ttl_seconds <= 0:
            raise ValueError("TTL values must be positive")
        self.max_sessions = max_sessions
        self.session_ttl_seconds = session_ttl_seconds
        self.pending_ttl_seconds = pending_ttl_seconds
        self._clock = clock
        self._records: OrderedDict[str, SessionRecord] = OrderedDict()
        self._lock = threading.Lock()

    def read(self, session_id: str) -> SessionRecord:
        with self._lock:
            now = self._clock()
            self._purge(now)
            record = self._records.get(session_id)
            if record is None:
                return SessionRecord(updated_at=now)
            self._expire_pending(record, now)
            self._records.move_to_end(session_id)
            return _copy_record(record)

    def now(self) -> float:
        return self._clock()

    def write(self, session_id: str, record: SessionRecord) -> None:
        with self._lock:
            now = self._clock()
            self._purge(now)
            stored = _copy_record(record)
            stored.updated_at = now
            self._records[session_id] = stored
            self._records.move_to_end(session_id)
            while len(self._records) > self.max_sessions:
                self._records.popitem(last=False)

    def consume_pending(
        self, session_id: str, action_id: str
    ) -> PendingAction | None:
        """Atomically remove before execution to provide at-most-once semantics."""

        with self._lock:
            now = self._clock()
            self._purge(now)
            record = self._records.get(session_id)
            if record is None:
                return None
            self._expire_pending(record, now)
            action = record.pending_action
            if action is None or action.id != action_id:
                return None
            record.pending_action = None
            record.updated_at = now
            self._records.move_to_end(session_id)
            return action

    def clear(self, session_id: str) -> bool:
        with self._lock:
            return self._records.pop(session_id, None) is not None

    def _purge(self, now: float) -> None:
        expired = [
            session_id
            for session_id, record in self._records.items()
            if now - record.updated_at >= self.session_ttl_seconds
        ]
        for session_id in expired:
            del self._records[session_id]

    def _expire_pending(self, record: SessionRecord, now: float) -> None:
        action = record.pending_action
        if action is not None and now - action.created_at >= self.pending_ttl_seconds:
            record.pending_action = None


class ConversationService:
    def __init__(
        self,
        *,
        registry: ToolRegistry,
        planner: Planner,
        store: InMemorySessionStore | None = None,
        booking_gateway: BookingGateway | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.registry = registry
        self.planner = planner
        self.store = store or InMemorySessionStore(clock=clock)
        self.booking_gateway = booking_gateway or DryRunBookingGateway()

    def chat(self, request: ChatRequest) -> AgentResponse:
        if request.session_id is None:
            return run_agent(
                _to_travel_request(request),
                registry=self.registry,
                planner=self.planner,
            )

        session_id = request.session_id
        record = self.store.read(session_id)
        enriched, recalled_fields = _enrich_request(request, record.memory)
        response = run_agent(enriched, registry=self.registry, planner=self.planner)
        updated_fields = _update_memory(record.memory, request)
        record.memory.turn_count += 1

        pending_action_id: str | None = None
        confirmation_status = "not_required"
        answer = response.answer
        if response.trace.needs_confirmation:
            if record.pending_action is None:
                record.pending_action = PendingAction(
                    id=uuid4().hex,
                    kind="booking",
                    summary=_booking_summary(enriched),
                    request=enriched,
                    created_at=self.store.now(),
                )
            pending_action_id = record.pending_action.id
            confirmation_status = "awaiting"
            answer = (
                f"待确认操作：{record.pending_action.summary}。"
                "请通过确认接口明确 approve 或 reject；确认前不会向外部服务提交。"
            )

        self.store.write(session_id, record)
        trace = response.trace.model_copy(
            update={
                "session_id": session_id,
                "memory_recalled": recalled_fields,
                "memory_updated": updated_fields,
                "pending_action_id": pending_action_id,
                "confirmation_status": confirmation_status,
            }
        )
        return response.model_copy(update={"answer": answer, "trace": trace})

    def confirm(
        self, session_id: str, request: ConfirmationRequest
    ) -> AgentResponse:
        action = self.store.consume_pending(session_id, request.action_id)
        if action is None:
            return _confirmation_response(
                session_id=session_id,
                status="invalid_or_expired",
                answer="确认令牌无效、已过期或已被处理；没有执行任何外部操作。",
            )
        if request.decision == "reject":
            return _confirmation_response(
                session_id=session_id,
                status="rejected",
                answer=f"已取消：{action.summary}。没有执行任何外部操作。",
                action=action,
            )

        try:
            result = self.booking_gateway.submit(action)
        except Exception as exc:  # noqa: BLE001
            return _confirmation_response(
                session_id=session_id,
                status="failed",
                answer="确认已收到，但预订服务执行失败；为防止重复提交，该令牌不能重放。",
                action=action,
                result={"error": str(exc)},
            )
        external_sent = bool(result.get("external_request_sent"))
        answer = (
            f"已确认并提交：{action.summary}。"
            if external_sent
            else f"已确认：{action.summary}。当前为 dry-run，没有向外部商家提交。"
        )
        return _confirmation_response(
            session_id=session_id,
            status="approved",
            answer=answer,
            action=action,
            result=result,
        )

    def clear(self, session_id: str) -> bool:
        return self.store.clear(session_id)


def _to_travel_request(request: ChatRequest) -> TravelRequest:
    return TravelRequest.model_validate(request.model_dump(exclude={"session_id"}))


def _enrich_request(
    request: ChatRequest, memory: SessionMemory
) -> tuple[TravelRequest, list[str]]:
    payload = request.model_dump(exclude={"session_id"})
    recalled: list[str] = []
    if request.location is None and memory.location is not None:
        payload["location"] = memory.location
        recalled.append("location")
        if memory.latitude is not None and memory.longitude is not None:
            payload["latitude"] = memory.latitude
            payload["longitude"] = memory.longitude
            recalled.extend(["latitude", "longitude"])
    if not request.preferences and memory.preferences:
        payload["preferences"] = list(memory.preferences)
        recalled.append("preferences")
    return TravelRequest.model_validate(payload), recalled


def _update_memory(memory: SessionMemory, request: ChatRequest) -> list[str]:
    updated: list[str] = []
    if request.location is not None:
        if memory.location != request.location:
            updated.append("location")
        memory.location = request.location
        memory.latitude = request.latitude
        memory.longitude = request.longitude
        if request.latitude is not None and request.longitude is not None:
            updated.extend(["latitude", "longitude"])
    if request.preferences:
        merged = list(dict.fromkeys([*memory.preferences, *request.preferences]))
        if merged != memory.preferences:
            updated.append("preferences")
        memory.preferences = merged
    return updated


def _booking_summary(request: TravelRequest) -> str:
    location = request.location or "未指定地点"
    preferences = "、".join(request.preferences) or "无额外偏好"
    return f"在{location}处理预订请求“{request.text}”（偏好：{preferences}）"


def _confirmation_response(
    *,
    session_id: str,
    status: str,
    answer: str,
    action: PendingAction | None = None,
    result: dict[str, Any] | None = None,
) -> AgentResponse:
    should_execute = action is not None and status in {"approved", "failed"}
    arguments = (
        {"action_id": action.id, "summary": action.summary}
        if action is not None
        else {}
    )
    plan = (
        [PlannedToolCall(name="submit_booking", arguments=arguments)]
        if should_execute
        else []
    )
    executions = []
    if should_execute:
        error = result.get("error") if result else None
        executions = [
            ToolExecution(
                name="submit_booking",
                arguments=arguments,
                output=None if error else result,
                error=error,
            )
        ]
    return AgentResponse(
        answer=answer,
        trace=AgentTrace(
            intents=["booking"],
            plan=plan,
            executions=executions,
            session_id=session_id,
            pending_action_id=action.id if action is not None else None,
            confirmation_status=status,
            confirmation_result=result,
        ),
    )


def _copy_record(record: SessionRecord) -> SessionRecord:
    action = record.pending_action
    return SessionRecord(
        memory=SessionMemory(
            location=record.memory.location,
            latitude=record.memory.latitude,
            longitude=record.memory.longitude,
            preferences=list(record.memory.preferences),
            turn_count=record.memory.turn_count,
        ),
        pending_action=(
            None
            if action is None
            else PendingAction(
                id=action.id,
                kind=action.kind,
                summary=action.summary,
                request=action.request.model_copy(deep=True),
                created_at=action.created_at,
            )
        ),
        updated_at=record.updated_at,
    )


def build_session_store_from_env() -> InMemorySessionStore:
    return InMemorySessionStore(
        max_sessions=int(os.getenv("SESSION_MAX_SESSIONS", "1000")),
        session_ttl_seconds=float(os.getenv("SESSION_TTL_SECONDS", "1800")),
        pending_ttl_seconds=float(
            os.getenv("PENDING_ACTION_TTL_SECONDS", "900")
        ),
    )


__all__ = [
    "BookingGateway",
    "ConversationService",
    "DryRunBookingGateway",
    "InMemorySessionStore",
    "PendingAction",
    "SessionMemory",
    "SessionRecord",
    "build_session_store_from_env",
]
