import argparse
import json
from pathlib import Path

from travel_agent.graph import run_agent
from travel_agent.models import TravelRequest
from travel_agent.planner import build_planner_from_env


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
    details = []
    for case in cases:
        response = run_agent(
            TravelRequest(
                text=case["text"],
                location=case.get("location"),
                preferences=case.get("preferences", []),
            ),
            planner=planner,
        )
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
            }
        )

    report = {
        "cases": len(cases),
        "passed": passed,
        "task_pass_rate": passed / len(cases) if cases else 0,
        "intent_accuracy": intent_passed / len(cases) if cases else 0,
        "tool_accuracy": tool_passed / len(cases) if cases else 0,
        "constraint_accuracy": constraint_passed / len(cases) if cases else 0,
        "details": details,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
