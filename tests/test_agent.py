from travel_agent.graph import run_agent
from travel_agent.models import TravelRequest


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

