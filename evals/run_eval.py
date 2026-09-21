import argparse
import json
import os
import time
from pathlib import Path

from travel_agent.graph import run_agent
from travel_agent.models import TravelRequest
from travel_agent.planner import build_planner_from_env


def percentile(values: list[int], fraction: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--planner", choices=["rule", "llm"], default="rule")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    planner = build_planner_from_env(args.planner)
    case_path = Path(__file__).with_name("cases.jsonl")
    cases = [
        json.loads(line)
        for line in case_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    passed = 0
    intent_passed = 0
    tool_passed = 0
    constraint_passed = 0
    native_llm_passed = 0
    planner_latencies: list[int] = []
    end_to_end_latencies: list[int] = []
    prompt_tokens = 0
    completion_tokens = 0
    fallback_count = 0
    repaired_count = 0
    models: set[str] = set()
    details = []
    for case in cases:
        started = time.perf_counter()
        response = run_agent(
            TravelRequest(
                text=case["text"],
                location=case.get("location"),
                preferences=case.get("preferences", []),
            ),
            planner=planner,
        )
        end_to_end_ms = round((time.perf_counter() - started) * 1000)
        tools = [call.name for call in response.trace.plan]
        intent_ok = response.trace.intents == case["expected_intents"]
        tool_ok = tools == case["expected_tools"]
        constraint_ok = (
            response.trace.missing_fields == case.get("expected_missing_fields", [])
            and response.trace.needs_confirmation == case.get("expected_confirmation", False)
        )
        ok = intent_ok and tool_ok and constraint_ok
        passed += int(ok)
        intent_passed += int(intent_ok)
        tool_passed += int(tool_ok)
        constraint_passed += int(constraint_ok)
        native_llm_passed += int(ok and response.trace.planner_used == "llm")
        planner_latencies.append(response.trace.planner_latency_ms)
        end_to_end_latencies.append(end_to_end_ms)
        prompt_tokens += response.trace.prompt_tokens or 0
        completion_tokens += response.trace.completion_tokens or 0
        fallback_count += int(response.trace.planner_used == "rule_fallback")
        repaired_count += int(response.trace.planner_repaired)
        if response.trace.planner_model:
            models.add(response.trace.planner_model)
        details.append(
            {
                "id": case["id"],
                "passed": ok,
                "intent_ok": intent_ok,
                "tool_ok": tool_ok,
                "constraint_ok": constraint_ok,
                "intents": response.trace.intents,
                "tools": tools,
                "planner_used": response.trace.planner_used,
                "planner_repaired": response.trace.planner_repaired,
                "planner_latency_ms": response.trace.planner_latency_ms,
                "end_to_end_latency_ms": end_to_end_ms,
                "prompt_tokens": response.trace.prompt_tokens,
                "completion_tokens": response.trace.completion_tokens,
            }
        )

    input_rate = float(os.getenv("LLM_INPUT_COST_PER_MILLION", "0"))
    output_rate = float(os.getenv("LLM_OUTPUT_COST_PER_MILLION", "0"))
    estimated_cost = (prompt_tokens * input_rate + completion_tokens * output_rate) / 1_000_000
    report = {
        "requested_planner": args.planner,
        "models": sorted(models),
        "cases": len(cases),
        "passed": passed,
        "task_pass_rate": passed / len(cases) if cases else 0,
        "intent_accuracy": intent_passed / len(cases) if cases else 0,
        "tool_accuracy": tool_passed / len(cases) if cases else 0,
        "constraint_accuracy": constraint_passed / len(cases) if cases else 0,
        "native_llm_task_pass_rate": (
            native_llm_passed / len(cases) if args.planner == "llm" and cases else None
        ),
        "fallback_count": fallback_count,
        "repair_count": repaired_count,
        "planner_latency_ms": {
            "p50": percentile(planner_latencies, 0.50),
            "p95": percentile(planner_latencies, 0.95),
        },
        "end_to_end_latency_ms": {
            "p50": percentile(end_to_end_latencies, 0.50),
            "p95": percentile(end_to_end_latencies, 0.95),
        },
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "estimated_cost_usd": round(estimated_cost, 6),
            "pricing_per_million_tokens": {
                "input": input_rate,
                "output": output_rate,
            },
        },
        "details": details,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
