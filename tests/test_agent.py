from travel_agent.graph import run_agent
from travel_agent.models import TravelRequest
from travel_agent.planner import LLMPlanner, ProviderResult


class DiningProvider:
    def generate_json(self, **_: object) -> ProviderResult:
        return ProviderResult(
            payload={
                "intents": ["dining"],
                "missing_fields": [],
                "tool_calls": [
                    {
                        "name": "search_poi",
                        "arguments": {"location": "难波", "preferences": ["不含肉"]},
                    },
                    {
                        "name": "translate_phrase",
                        "arguments": {
                            "text": "肚子饿了，周围有无不含肉的店",
                            "target_language": "ja",
                            "preferences": ["不含肉"],
                        },
                    },
                ],
                "needs_confirmation": False,
            }
        )


def test_dining_and_translation_use_expected_tools() -> None:
    response = run_agent(
        TravelRequest(
            text="我在大阪站附近，找一家支持素食的餐厅，并生成一句日语询问语",
            location="大阪站",
            preferences=["素食"],
        )
    )

    assert "Green Table Umeda" in response.answer
    assert "ベジタリアン" in response.answer
    assert response.trace.intents == ["dining", "translation"]
    assert [call.name for call in response.trace.plan] == ["search_poi", "translate_phrase"]


def test_itinerary_checks_weather() -> None:
    response = run_agent(
        TravelRequest(text="帮我安排大阪站附近三小时的景点行程", location="大阪站")
    )

    assert "雨具" in response.answer
    assert [call.name for call in response.trace.plan] == ["search_poi", "get_weather"]


def test_unknown_request_is_honest_about_mock_limit() -> None:
    response = run_agent(TravelRequest(text="你好"))

    assert response.trace.intents == ["general"]
    assert "还不支持" in response.answer


def test_agent_can_use_llm_planner_for_semantic_request() -> None:
    response = run_agent(
        TravelRequest(
            text="肚子饿了，周围有无不含肉的店",
            location="难波",
            preferences=["不含肉"],
        ),
        planner=LLMPlanner(DiningProvider()),
    )

    assert response.trace.planner_used == "llm"
    assert response.trace.intents == ["dining"]
    assert "Green Table Umeda" in response.answer


def test_missing_location_stops_before_tool_execution() -> None:
    response = run_agent(TravelRequest(text="附近有什么素食餐厅", preferences=["素食"]))

    assert response.trace.missing_fields == ["location"]
    assert response.trace.needs_confirmation
    assert response.trace.executions == []
    assert "location" in response.answer
