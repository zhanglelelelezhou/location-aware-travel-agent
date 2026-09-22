from fastapi.testclient import TestClient

from travel_agent.api import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "provider": "mock"}


def test_chat_returns_trace() -> None:
    response = client.post(
        "/v1/chat",
        json={"text": "帮我找素食餐厅并翻译成日语", "location": "大阪站", "preferences": ["素食"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["trace"]["executions"]
    assert "answer" in body


def test_chat_rejects_incomplete_coordinate_pair() -> None:
    response = client.post(
        "/v1/chat",
        json={"text": "东京天气", "location": "东京", "latitude": 35.6895},
    )

    assert response.status_code == 422


def test_api_recalls_location_within_explicit_session() -> None:
    session_id = "api-memory-session"
    client.delete(f"/v1/sessions/{session_id}")
    first = client.post(
        "/v1/chat",
        json={
            "text": "记住我的位置和偏好",
            "session_id": session_id,
            "location": "京都站",
            "preferences": ["素食"],
        },
    )
    second = client.post(
        "/v1/chat",
        json={"text": "附近找一家餐厅", "session_id": session_id},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    trace = second.json()["trace"]
    assert trace["memory_recalled"] == ["location", "preferences"]
    assert trace["plan"][0]["arguments"]["location"] == "京都站"


def test_api_booking_requires_separate_one_time_confirmation() -> None:
    session_id = "api-booking-session"
    client.delete(f"/v1/sessions/{session_id}")
    pending = client.post(
        "/v1/chat",
        json={
            "text": "帮我预约晚餐",
            "session_id": session_id,
            "location": "大阪",
        },
    )
    action_id = pending.json()["trace"]["pending_action_id"]

    approved = client.post(
        f"/v1/sessions/{session_id}/confirm",
        json={"action_id": action_id, "decision": "approve"},
    )
    replay = client.post(
        f"/v1/sessions/{session_id}/confirm",
        json={"action_id": action_id, "decision": "approve"},
    )

    assert pending.json()["trace"]["executions"] == []
    assert pending.json()["trace"]["confirmation_status"] == "awaiting"
    assert approved.json()["trace"]["confirmation_status"] == "approved"
    assert approved.json()["trace"]["confirmation_result"]["provider"] == "dry-run"
    assert replay.json()["trace"]["confirmation_status"] == "invalid_or_expired"
