from __future__ import annotations

from typing import Any

from travel_agent.models import ChatRequest, ConfirmationRequest
from travel_agent.planner import RulePlanner
from travel_agent.session import ConversationService, InMemorySessionStore
from travel_agent.tools import build_mock_registry


class RecordingBookingGateway:
    def __init__(self) -> None:
        self.actions: list[str] = []

    def submit(self, action: Any) -> dict[str, Any]:
        self.actions.append(action.id)
        return {
            "status": "accepted",
            "provider": "recording-test",
            "external_request_sent": True,
            "action_id": action.id,
        }


class FailingBookingGateway:
    def __init__(self) -> None:
        self.calls = 0

    def submit(self, action: Any) -> dict[str, Any]:
        self.calls += 1
        raise TimeoutError(f"booking timeout for {action.id}")


def build_service(
    *,
    store: InMemorySessionStore | None = None,
    gateway: RecordingBookingGateway | None = None,
) -> ConversationService:
    return ConversationService(
        registry=build_mock_registry(),
        planner=RulePlanner(),
        store=store,
        booking_gateway=gateway,
    )


def test_session_recalls_only_structured_location_and_preferences() -> None:
    service = build_service()
    first = service.chat(
        ChatRequest(
            text="先记住我的旅行条件",
            session_id="memory-1",
            location="京都站",
            latitude=34.9858,
            longitude=135.7588,
            preferences=["素食"],
        )
    )
    second = service.chat(
        ChatRequest(text="附近找一家餐厅", session_id="memory-1")
    )

    assert first.trace.memory_updated == [
        "location",
        "latitude",
        "longitude",
        "preferences",
    ]
    assert second.trace.memory_recalled == [
        "location",
        "latitude",
        "longitude",
        "preferences",
    ]
    poi_call = second.trace.plan[0]
    assert poi_call.arguments["location"] == "京都站"
    assert poi_call.arguments["latitude"] == 34.9858
    assert poi_call.arguments["preferences"] == ["素食"]


def test_explicit_new_location_overrides_memory_and_drops_old_coordinates() -> None:
    service = build_service()
    service.chat(
        ChatRequest(
            text="记住位置",
            session_id="memory-override",
            location="东京",
            latitude=35.6895,
            longitude=139.6917,
        )
    )
    response = service.chat(
        ChatRequest(
            text="大阪天气怎么样",
            session_id="memory-override",
            location="大阪",
        )
    )

    assert response.trace.memory_recalled == []
    assert response.trace.plan[0].arguments["location"] == "大阪"
    assert response.trace.plan[0].arguments["latitude"] is None
    assert response.trace.plan[0].arguments["longitude"] is None


def test_sessions_do_not_share_memory() -> None:
    service = build_service()
    service.chat(
        ChatRequest(text="记住位置", session_id="session-a", location="东京")
    )

    response = service.chat(
        ChatRequest(text="附近找一家餐厅", session_id="session-b")
    )

    assert response.trace.memory_recalled == []
    assert response.trace.missing_fields == ["location"]


def test_booking_is_not_submitted_before_explicit_approval() -> None:
    gateway = RecordingBookingGateway()
    service = build_service(gateway=gateway)

    response = service.chat(
        ChatRequest(
            text="帮我预约一家素食餐厅",
            session_id="booking-approve",
            location="大阪",
            preferences=["素食"],
        )
    )

    assert gateway.actions == []
    assert response.trace.needs_confirmation
    assert response.trace.confirmation_status == "awaiting"
    assert response.trace.pending_action_id
    assert response.trace.executions == []

    approved = service.confirm(
        "booking-approve",
        ConfirmationRequest(
            action_id=response.trace.pending_action_id,
            decision="approve",
        ),
    )

    assert gateway.actions == [response.trace.pending_action_id]
    assert approved.trace.confirmation_status == "approved"
    assert approved.trace.confirmation_result is not None
    assert approved.trace.confirmation_result["external_request_sent"] is True
    assert [call.name for call in approved.trace.plan] == ["submit_booking"]
    assert approved.trace.executions[0].output == approved.trace.confirmation_result


def test_confirmation_token_is_bound_to_session_and_at_most_once() -> None:
    gateway = RecordingBookingGateway()
    service = build_service(gateway=gateway)
    pending = service.chat(
        ChatRequest(
            text="预约晚餐",
            session_id="booking-owner",
            location="京都",
        )
    )
    action_id = pending.trace.pending_action_id
    assert action_id is not None

    wrong_session = service.confirm(
        "booking-attacker",
        ConfirmationRequest(action_id=action_id, decision="approve"),
    )
    approved = service.confirm(
        "booking-owner",
        ConfirmationRequest(action_id=action_id, decision="approve"),
    )
    replay = service.confirm(
        "booking-owner",
        ConfirmationRequest(action_id=action_id, decision="approve"),
    )

    assert wrong_session.trace.confirmation_status == "invalid_or_expired"
    assert approved.trace.confirmation_status == "approved"
    assert replay.trace.confirmation_status == "invalid_or_expired"
    assert gateway.actions == [action_id]


def test_rejection_never_calls_booking_gateway() -> None:
    gateway = RecordingBookingGateway()
    service = build_service(gateway=gateway)
    pending = service.chat(
        ChatRequest(
            text="帮我订一桌",
            session_id="booking-reject",
            location="东京",
        )
    )
    assert pending.trace.pending_action_id is not None

    rejected = service.confirm(
        "booking-reject",
        ConfirmationRequest(
            action_id=pending.trace.pending_action_id,
            decision="reject",
        ),
    )

    assert rejected.trace.confirmation_status == "rejected"
    assert gateway.actions == []


def test_session_and_pending_action_expire_with_bounded_ttl() -> None:
    now = [100.0]
    store = InMemorySessionStore(
        session_ttl_seconds=20,
        pending_ttl_seconds=5,
        clock=lambda: now[0],
    )
    gateway = RecordingBookingGateway()
    service = build_service(store=store, gateway=gateway)
    pending = service.chat(
        ChatRequest(
            text="预约晚餐",
            session_id="booking-expire",
            location="大阪",
        )
    )
    assert pending.trace.pending_action_id is not None
    now[0] += 6

    expired = service.confirm(
        "booking-expire",
        ConfirmationRequest(
            action_id=pending.trace.pending_action_id,
            decision="approve",
        ),
    )

    assert expired.trace.confirmation_status == "invalid_or_expired"
    assert gateway.actions == []


def test_session_memory_expires_instead_of_recalling_stale_location() -> None:
    now = [100.0]
    store = InMemorySessionStore(
        session_ttl_seconds=5,
        pending_ttl_seconds=5,
        clock=lambda: now[0],
    )
    service = build_service(store=store)
    service.chat(
        ChatRequest(text="记住位置", session_id="memory-expire", location="东京")
    )
    now[0] += 6

    response = service.chat(
        ChatRequest(text="附近找一家餐厅", session_id="memory-expire")
    )

    assert response.trace.memory_recalled == []
    assert response.trace.missing_fields == ["location"]


def test_gateway_failure_is_audited_and_token_cannot_be_replayed() -> None:
    gateway = FailingBookingGateway()
    service = ConversationService(
        registry=build_mock_registry(),
        planner=RulePlanner(),
        booking_gateway=gateway,
    )
    pending = service.chat(
        ChatRequest(
            text="预约晚餐",
            session_id="booking-failure",
            location="东京",
        )
    )
    action_id = pending.trace.pending_action_id
    assert action_id is not None

    failed = service.confirm(
        "booking-failure",
        ConfirmationRequest(action_id=action_id, decision="approve"),
    )
    replay = service.confirm(
        "booking-failure",
        ConfirmationRequest(action_id=action_id, decision="approve"),
    )

    assert failed.trace.confirmation_status == "failed"
    assert failed.trace.executions[0].error == f"booking timeout for {action_id}"
    assert replay.trace.confirmation_status == "invalid_or_expired"
    assert gateway.calls == 1
