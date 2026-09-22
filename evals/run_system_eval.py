from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from collections import Counter
from pathlib import Path
from typing import Any

from travel_agent.models import ChatRequest, ConfirmationRequest
from travel_agent.planner import RulePlanner
from travel_agent.session import (
    ConversationService,
    DryRunBookingGateway,
    PendingAction,
)
from travel_agent.streaming import stream_conversation
from travel_agent.tools import build_mock_registry
from travel_agent.tools.base import ToolRegistry
from travel_agent.tools.mock import (
    MockPoiSearchTool,
    MockTranslateTool,
    MockTravelKnowledgeTool,
)

ROOT = Path(__file__).parents[1]
DEFAULT_CASES = ROOT / "evals" / "system_cases.jsonl"

ERROR_TAXONOMY = (
    "intent_mismatch",
    "tool_mismatch",
    "constraint_mismatch",
    "answer_evidence_missing",
    "memory_mismatch",
    "confirmation_mismatch",
    "lifecycle_mismatch",
    "recovery_mismatch",
    "runtime_error",
)

CHECK_TO_ERROR = {
    "intent": "intent_mismatch",
    "tools": "tool_mismatch",
    "arguments": "tool_mismatch",
    "constraints": "constraint_mismatch",
    "answer": "answer_evidence_missing",
    "memory": "memory_mismatch",
    "confirmation": "confirmation_mismatch",
    "safety": "confirmation_mismatch",
    "lifecycle": "lifecycle_mismatch",
    "recovery": "recovery_mismatch",
}


class CountingDryRunBookingGateway(DryRunBookingGateway):
    def __init__(self) -> None:
        self.submissions: list[str] = []

    def submit(self, action: PendingAction) -> dict[str, Any]:
        self.submissions.append(action.id)
        return super().submit(action)


class FailingWeatherTool:
    name = "get_weather"
    description = "Deterministic failure used by the acceptance evaluator."

    def invoke(self, arguments: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("injected weather failure")


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    ids = [case["id"] for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("system evaluation case IDs must be unique")
    return cases


def build_service(
    *,
    registry: ToolRegistry | None = None,
    gateway: CountingDryRunBookingGateway | None = None,
) -> ConversationService:
    return ConversationService(
        registry=registry or build_mock_registry(),
        planner=RulePlanner(),
        booking_gateway=gateway,
    )


def evaluate(cases_path: Path = DEFAULT_CASES) -> dict[str, Any]:
    cases_path = cases_path.resolve()
    cases = load_cases(cases_path)
    details: list[dict[str, Any]] = []
    latencies_ms: list[float] = []
    check_totals: Counter[str] = Counter()
    check_passed: Counter[str] = Counter()
    taxonomy_counts: Counter[str] = Counter()
    category_totals: Counter[str] = Counter()
    category_passed: Counter[str] = Counter()

    for case in cases:
        started = time.perf_counter()
        try:
            detail = evaluate_case(case)
        except Exception as exc:  # noqa: BLE001
            detail = {
                "id": case["id"],
                "category": case["category"],
                "passed": False,
                "checks": {"runtime": False},
                "errors": ["runtime_error"],
                "actual": {
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                },
            }
        latency_ms = (time.perf_counter() - started) * 1000
        detail["latency_ms"] = round(latency_ms, 3)
        latencies_ms.append(latency_ms)
        details.append(detail)

        category = case["category"]
        category_totals[category] += 1
        category_passed[category] += int(detail["passed"])
        for check, passed in detail["checks"].items():
            check_totals[check] += 1
            check_passed[check] += int(passed)
        taxonomy_counts.update(detail["errors"])

    passed_count = sum(int(detail["passed"]) for detail in details)
    failures = [detail for detail in details if not detail["passed"]]
    return {
        "evaluation": "system-acceptance-v1",
        "scoring_policy": "all-applicable-contract-checks-must-pass",
        "environment": {
            "planner": "rule",
            "tools": "mock",
            "network_required": False,
        },
        "dataset": {
            "path": _relative_path(cases_path),
            "sha256": hashlib.sha256(cases_path.read_bytes()).hexdigest(),
            "case_count": len(cases),
            "category_counts": dict(sorted(category_totals.items())),
        },
        "passed": passed_count,
        "task_pass_rate": passed_count / len(cases) if cases else 0.0,
        "dimension_accuracy": {
            check: check_passed[check] / total
            for check, total in sorted(check_totals.items())
        },
        "category_pass_rate": {
            category: category_passed[category] / total
            for category, total in sorted(category_totals.items())
        },
        "latency_ms": {
            "p50": round(_percentile(latencies_ms, 0.50), 3),
            "p95": round(_percentile(latencies_ms, 0.95), 3),
        },
        "error_taxonomy": {
            error: taxonomy_counts[error] for error in ERROR_TAXONOMY
        },
        "failure_count": len(failures),
        "failures": failures,
        "details": details,
    }


def evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    category = case["category"]
    if category == "single_turn":
        return _evaluate_single_turn(case)
    if category == "session":
        return _evaluate_session(case)
    if category == "confirmation":
        return _evaluate_confirmation(case)
    if category == "stream":
        return _evaluate_stream(case)
    raise ValueError(f"Unsupported system evaluation category: {category}")


def _evaluate_single_turn(case: dict[str, Any]) -> dict[str, Any]:
    response = build_service().chat(ChatRequest.model_validate(case["request"]))
    checks, actual = _response_checks(response, case["expected"])
    return _detail(case, checks, actual)


def _evaluate_session(case: dict[str, Any]) -> dict[str, Any]:
    service = build_service()
    session_id = f"eval-{case['id']}"
    for setup in case.get("setup", []):
        service.chat(ChatRequest.model_validate({**setup, "session_id": session_id}))
    response = service.chat(
        ChatRequest.model_validate({**case["request"], "session_id": session_id})
    )
    checks, actual = _response_checks(response, case["expected"])
    expected_memory = case["expected"].get("memory_recalled")
    if expected_memory is not None:
        checks["memory"] = response.trace.memory_recalled == expected_memory
        actual["memory_recalled"] = response.trace.memory_recalled
    return _detail(case, checks, actual)


def _evaluate_confirmation(case: dict[str, Any]) -> dict[str, Any]:
    gateway = CountingDryRunBookingGateway()
    service = build_service(gateway=gateway)
    session_id = f"eval-{case['id']}"
    for setup in case.get("setup", []):
        service.chat(ChatRequest.model_validate({**setup, "session_id": session_id}))
    pending = service.chat(
        ChatRequest.model_validate({**case["request"], "session_id": session_id})
    )
    action_id = pending.trace.pending_action_id
    expected = case["expected"]
    checks = {
        "confirmation": (
            action_id is not None
            and pending.trace.confirmation_status == expected["initial_status"]
        ),
        "safety": pending.trace.executions == [],
    }
    final_status: str | None = None
    replay_status: str | None = None
    external_request_sent: bool | None = None
    if action_id is not None:
        operation = case["operation"]
        decision = "reject" if operation == "reject" else "approve"
        confirmation_session = (
            f"{session_id}-wrong" if operation == "wrong_session" else session_id
        )
        confirmed = service.confirm(
            confirmation_session,
            ConfirmationRequest(action_id=action_id, decision=decision),
        )
        final_status = confirmed.trace.confirmation_status
        result = confirmed.trace.confirmation_result or {}
        external_request_sent = result.get("external_request_sent")
        if operation == "replay":
            replay = service.confirm(
                session_id,
                ConfirmationRequest(action_id=action_id, decision="approve"),
            )
            replay_status = replay.trace.confirmation_status

    checks["confirmation"] = checks["confirmation"] and (
        final_status == expected["final_status"]
        and (
            "replay_status" not in expected
            or replay_status == expected["replay_status"]
        )
        and (
            "external_request_sent" not in expected
            or external_request_sent == expected["external_request_sent"]
        )
    )
    checks["safety"] = checks["safety"] and (
        len(gateway.submissions) == expected["gateway_execution_count"]
    )
    if "memory_recalled" in expected:
        checks["memory"] = (
            pending.trace.memory_recalled == expected["memory_recalled"]
        )
    actual = {
        "initial_status": pending.trace.confirmation_status,
        "pending_action_id_present": action_id is not None,
        "final_status": final_status,
        "replay_status": replay_status,
        "external_request_sent": external_request_sent,
        "gateway_execution_count": len(gateway.submissions),
        "memory_recalled": pending.trace.memory_recalled,
    }
    return _detail(case, checks, actual)


def _evaluate_stream(case: dict[str, Any]) -> dict[str, Any]:
    registry = None
    if case.get("failure_tool") == "get_weather":
        registry = ToolRegistry(
            [
                MockPoiSearchTool(),
                FailingWeatherTool(),
                MockTranslateTool(),
                MockTravelKnowledgeTool(),
            ],
            provider="eval-failure",
        )
    frames = list(
        stream_conversation(
            build_service(registry=registry),
            ChatRequest.model_validate(case["request"]),
        )
    )
    events = _parse_sse_frames(frames)
    event_types = [event["type"] for event in events]
    expected = case["expected"]
    lifecycle_ok = _events_match(event_types, expected)
    sequence_ok = [event["sequence"] for event in events] == list(
        range(1, len(events) + 1)
    )
    final_response = (
        events[-1].get("data", {}).get("response", {}) if events else {}
    )
    answer = final_response.get("answer", "")
    lifecycle_ok = lifecycle_ok and all(
        text in answer for text in expected.get("answer_contains", [])
    )
    if "confirmation_status" in expected:
        lifecycle_ok = lifecycle_ok and (
            final_response.get("trace", {}).get("confirmation_status")
            == expected["confirmation_status"]
        )
    recovery_ok = True
    if "retry_count" in expected:
        recovery_ok = (
            final_response.get("trace", {}).get("retry_count")
            == expected["retry_count"]
        )
    checks = {
        "lifecycle": lifecycle_ok and sequence_ok,
        "recovery": recovery_ok,
    }
    actual = {
        "events": event_types,
        "sequences": [event["sequence"] for event in events],
        "answer": answer,
        "retry_count": final_response.get("trace", {}).get("retry_count"),
        "confirmation_status": final_response.get("trace", {}).get(
            "confirmation_status"
        ),
    }
    return _detail(case, checks, actual)


def _response_checks(
    response: Any, expected: dict[str, Any]
) -> tuple[dict[str, bool], dict[str, Any]]:
    tools = [call.name for call in response.trace.plan]
    checks = {
        "intent": set(response.trace.intents) == set(expected["intents"]),
        "tools": set(tools) == set(expected["tools"]),
        "constraints": (
            response.trace.missing_fields == expected.get("missing_fields", [])
            and response.trace.needs_confirmation
            == expected.get("needs_confirmation", False)
        ),
        "answer": all(
            text in response.answer for text in expected.get("answer_contains", [])
        ),
    }
    expected_arguments = expected.get("tool_arguments", {})
    if expected_arguments:
        actual_calls = {call.name: call.arguments for call in response.trace.plan}
        checks["arguments"] = all(
            tool in actual_calls
            and all(actual_calls[tool].get(key) == value for key, value in subset.items())
            for tool, subset in expected_arguments.items()
        )
    actual = {
        "intents": response.trace.intents,
        "tools": tools,
        "missing_fields": response.trace.missing_fields,
        "needs_confirmation": response.trace.needs_confirmation,
        "answer": response.answer,
        "tool_arguments": {
            call.name: call.arguments for call in response.trace.plan
        },
    }
    return checks, actual


def _events_match(event_types: list[str], expected: dict[str, Any]) -> bool:
    if "events" in expected and event_types != expected["events"]:
        return False
    if any(event in event_types for event in expected.get("forbidden_events", [])):
        return False
    if not all(event in event_types for event in expected.get("required_events", [])):
        return False
    counts = Counter(event_types)
    return all(
        counts[event] == expected_count
        for event, expected_count in expected.get("event_counts", {}).items()
    )


def _parse_sse_frames(frames: list[str]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for frame in frames:
        if frame.startswith(":"):
            continue
        data_line = next(
            line[6:] for line in frame.splitlines() if line.startswith("data: ")
        )
        events.append(json.loads(data_line))
    return events


def _detail(
    case: dict[str, Any], checks: dict[str, bool], actual: dict[str, Any]
) -> dict[str, Any]:
    errors = sorted(
        {
            CHECK_TO_ERROR[check]
            for check, passed in checks.items()
            if not passed and check in CHECK_TO_ERROR
        }
    )
    return {
        "id": case["id"],
        "category": case["category"],
        "passed": all(checks.values()),
        "checks": checks,
        "errors": errors,
        "actual": actual,
    }


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def _relative_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run deterministic end-to-end system acceptance evaluation."
    )
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--min-pass-rate",
        type=float,
        default=1.0,
        help="Exit non-zero when task pass rate is below this threshold.",
    )
    args = parser.parse_args()
    if not 0.0 <= args.min_pass_rate <= 1.0:
        parser.error("--min-pass-rate must be between 0 and 1")
    report = evaluate(args.cases)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if report["task_pass_rate"] < args.min_pass_rate:
        raise SystemExit(
            "system acceptance gate failed: "
            f"{report['task_pass_rate']:.1%} < {args.min_pass_rate:.1%}"
        )


if __name__ == "__main__":
    main()
