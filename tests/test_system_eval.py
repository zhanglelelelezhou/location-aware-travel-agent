from __future__ import annotations

import hashlib
import importlib.util
import json
from collections import Counter
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).parents[1]
SYSTEM_CASES_SHA256 = (
    "ad50e28be5c002baafee1c8385bd3d918ce221713198d0c7cae4db67ff1bd0c3"
)


def load_system_eval_module() -> ModuleType:
    path = ROOT / "evals" / "run_system_eval.py"
    spec = importlib.util.spec_from_file_location("run_system_eval", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_cases(path: Path, cases: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(
            json.dumps(case, ensure_ascii=False) + "\n" for case in cases
        ),
        encoding="utf-8",
    )


def test_system_acceptance_cases_are_frozen_by_hash_and_distribution() -> None:
    cases_path = ROOT / "evals" / "system_cases.jsonl"
    module = load_system_eval_module()
    cases = module.load_cases(cases_path)

    assert hashlib.sha256(cases_path.read_bytes()).hexdigest() == (
        SYSTEM_CASES_SHA256
    )
    assert len(cases) == 30
    assert Counter(case["category"] for case in cases) == {
        "single_turn": 16,
        "session": 5,
        "confirmation": 5,
        "stream": 4,
    }


def test_system_eval_rejects_duplicate_case_ids(tmp_path: Path) -> None:
    module = load_system_eval_module()
    cases_path = tmp_path / "duplicate-cases.jsonl"
    write_cases(
        cases_path,
        [
            {"id": "duplicate", "category": "single_turn"},
            {"id": "duplicate", "category": "stream"},
        ],
    )

    with pytest.raises(ValueError, match="case IDs must be unique"):
        module.load_cases(cases_path)


def test_system_eval_classifies_contract_failures(tmp_path: Path) -> None:
    module = load_system_eval_module()
    cases_path = tmp_path / "failure-case.jsonl"
    write_cases(
        cases_path,
        [
            {
                "id": "synthetic_contract_failure",
                "category": "single_turn",
                "request": {"text": "你好"},
                "expected": {
                    "intents": ["weather"],
                    "tools": [],
                    "missing_fields": [],
                    "needs_confirmation": False,
                    "answer_contains": ["不存在的证据"],
                },
            }
        ],
    )

    report = module.evaluate(cases_path)

    assert report["passed"] == 0
    assert report["task_pass_rate"] == 0.0
    assert report["failure_count"] == 1
    assert report["error_taxonomy"]["intent_mismatch"] == 1
    assert report["error_taxonomy"]["answer_evidence_missing"] == 1
    assert set(report["failures"][0]["errors"]) == {
        "intent_mismatch",
        "answer_evidence_missing",
    }


def test_system_eval_accepts_valid_stream_lifecycle(tmp_path: Path) -> None:
    module = load_system_eval_module()
    cases_path = tmp_path / "stream-case.jsonl"
    write_cases(
        cases_path,
        [
            {
                "id": "synthetic_stream_success",
                "category": "stream",
                "request": {"text": "大阪天气怎么样", "location": "大阪"},
                "expected": {
                    "required_events": [
                        "request.accepted",
                        "planning.started",
                        "tool.started",
                        "tool.completed",
                        "response.completed",
                    ],
                    "forbidden_events": ["recovery.started"],
                    "answer_contains": ["当前天气"],
                    "retry_count": 0,
                },
            }
        ],
    )

    report = module.evaluate(cases_path)

    assert report["passed"] == 1
    assert report["task_pass_rate"] == 1.0
    assert report["failure_count"] == 0
    assert report["dimension_accuracy"] == {
        "lifecycle": 1.0,
        "recovery": 1.0,
    }


def test_frozen_system_acceptance_suite_meets_ci_gate() -> None:
    module = load_system_eval_module()

    report = module.evaluate()

    assert report["dataset"]["sha256"] == SYSTEM_CASES_SHA256
    assert report["dataset"]["case_count"] == 30
    assert report["passed"] == 30
    assert report["task_pass_rate"] == 1.0
    assert report["failure_count"] == 0
