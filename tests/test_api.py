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

