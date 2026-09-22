from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import pytest

from travel_agent.graph import run_agent
from travel_agent.models import TravelRequest
from travel_agent.tools import build_tool_registry_from_env
from travel_agent.tools.knowledge import (
    KnowledgeSearchResult,
    LocalTravelKnowledgeTool,
)


def test_knowledge_tool_retrieves_cited_allergy_guidance() -> None:
    result = LocalTravelKnowledgeTool().invoke(
        {"query": "我对花生严重过敏，在日本餐厅点餐要确认什么？", "top_k": 2}
    )
    parsed = KnowledgeSearchResult.model_validate(result)

    assert parsed.retrieval_method == "bm25"
    assert parsed.passages[0].id == "jp-restaurant-allergy-cross-contact"
    assert parsed.passages[0].source.startswith("https://www.caa.go.jp/")
    assert parsed.passages[0].score > 0


def test_knowledge_tool_supports_english_emergency_queries() -> None:
    result = LocalTravelKnowledgeTool().invoke(
        {"query": "What number should I call for police in Japan?", "top_k": 1}
    )

    assert result["passages"][0]["id"] == "jp-emergency-numbers"
    assert "110" in result["passages"][0]["text"]


def test_knowledge_tool_rejects_out_of_domain_query() -> None:
    result = LocalTravelKnowledgeTool().invoke(
        {"query": "日本租车需要儿童座椅吗"}
    )

    assert result["minimum_score"] == 1.0
    assert result["passages"] == []


@pytest.mark.parametrize(
    "arguments, message",
    [
        ({"query": ""}, "non-empty"),
        ({"query": "地震", "top_k": 10}, "between 1 and 5"),
        ({"query": "地震", "top_k": True}, "between 1 and 5"),
    ],
)
def test_knowledge_tool_rejects_invalid_arguments(
    arguments: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        LocalTravelKnowledgeTool().invoke(arguments)


def test_open_data_agent_returns_source_link_for_safety_guidance() -> None:
    response = run_agent(
        TravelRequest(text="我对花生严重过敏，在日本餐厅点餐要注意什么"),
        registry=build_tool_registry_from_env("open-data"),
    )

    assert "交叉接触" in response.answer
    assert "https://www.caa.go.jp/" in response.answer


@pytest.mark.parametrize(
    "query, expected_id",
    [
        ("在日本遇到地震应该怎么办", "jp-earthquake-actions"),
        ("护照丢了应该去哪里报案", "jp-lost-passport-police-report"),
        ("游客生病了怎么寻找医院", "jp-medical-assistance"),
    ],
)
def test_rule_agent_routes_travel_safety_topics_to_knowledge(
    query: str, expected_id: str
) -> None:
    response = run_agent(
        TravelRequest(text=query),
        registry=build_tool_registry_from_env("open-data"),
    )

    assert [call.name for call in response.trace.plan] == ["search_travel_knowledge"]
    assert response.trace.executions[0].output is not None
    assert response.trace.executions[0].output["passages"][0]["id"] == expected_id


def test_bm25_baseline_meets_frozen_retrieval_threshold() -> None:
    path = Path(__file__).parents[1] / "evals" / "run_knowledge_eval.py"
    spec = importlib.util.spec_from_file_location("run_knowledge_eval", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    report = module.evaluate()

    assert report["case_count"] == 12
    assert report["hit_at_1"] >= 0.80
    assert report["hit_at_k"] == 1.0
    assert report["recall_at_k"] >= 0.90
    assert report["rejection_case_count"] == 6
    assert report["rejection_accuracy"] == 1.0


def test_knowledge_cases_and_corpus_are_versioned_by_hash() -> None:
    root = Path(__file__).parents[1]
    cases = root / "evals" / "knowledge_cases.jsonl"
    rejection_cases = root / "evals" / "knowledge_rejection_cases.jsonl"
    corpus = (
        root
        / "src"
        / "travel_agent"
        / "data"
        / "knowledge"
        / "japan_travel_safety.json"
    )

    assert hashlib.sha256(cases.read_bytes()).hexdigest() == (
        "3823d6656c7957a610c186969725f9cc93792e0808ecf601507fabce91e36bb8"
    )
    assert hashlib.sha256(rejection_cases.read_bytes()).hexdigest() == (
        "570d848b8e48d8693eb3eccaa14de4895ca8d67a5d4020cd05bb6600da631506"
    )
    assert hashlib.sha256(corpus.read_bytes()).hexdigest() == (
        "eb14d9f3ebd73012ba2c475b39c1cd0ed3a47eddef36af76a49d698fac89f10e"
    )
