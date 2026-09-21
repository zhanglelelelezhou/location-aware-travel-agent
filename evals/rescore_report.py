import argparse
import json
from pathlib import Path
from typing import Any


def load_cases(path: Path) -> dict[str, dict[str, Any]]:
    return {
        case["id"]: case
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
        for case in [json.loads(line)]
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Rescore saved predictions without API calls.")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--cases",
        type=Path,
        default=Path(__file__).with_name("cases.jsonl"),
    )
    args = parser.parse_args()

    report = json.loads(args.input.read_text(encoding="utf-8"))
    cases = load_cases(args.cases)
    passed = intent_passed = tool_passed = constraint_passed = native_llm_passed = 0

    for detail in report["details"]:
        case = cases[detail["id"]]
        intent_ok = set(detail["intents"]) == set(case["expected_intents"])
        tool_ok = set(detail["tools"]) == set(case["expected_tools"])
        constraint_ok = (
            detail.get("missing_fields", []) == case.get("expected_missing_fields", [])
            and detail.get("needs_confirmation", False)
            == case.get("expected_confirmation", False)
        )
        ok = intent_ok and tool_ok and constraint_ok
        detail.update(
            passed=ok,
            intent_ok=intent_ok,
            tool_ok=tool_ok,
            constraint_ok=constraint_ok,
        )
        passed += int(ok)
        intent_passed += int(intent_ok)
        tool_passed += int(tool_ok)
        constraint_passed += int(constraint_ok)
        native_llm_passed += int(ok and detail["planner_used"] == "llm")

    total = len(report["details"])
    report.update(
        scoring_policy="intent-set_tool-set_constraints-v2",
        cases=total,
        passed=passed,
        task_pass_rate=passed / total,
        intent_accuracy=intent_passed / total,
        tool_accuracy=tool_passed / total,
        constraint_accuracy=constraint_passed / total,
        native_llm_task_pass_rate=(
            native_llm_passed / total if report["requested_planner"] == "llm" else None
        ),
        rescored_from=str(args.input),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
