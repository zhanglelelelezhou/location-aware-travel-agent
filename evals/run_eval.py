import json
from pathlib import Path

from travel_agent.graph import run_agent
from travel_agent.models import TravelRequest


def main() -> None:
    case_path = Path(__file__).with_name("cases.jsonl")
    cases = [
        json.loads(line)
        for line in case_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    passed = 0
    details = []
    for case in cases:
        response = run_agent(
            TravelRequest(
                text=case["text"],
                location=case.get("location"),
                preferences=case.get("preferences", []),
            )
        )
        tools = [call.name for call in response.trace.plan]
        ok = response.trace.intents == case["expected_intents"] and tools == case["expected_tools"]
        passed += int(ok)
        details.append({"id": case["id"], "passed": ok, "intents": response.trace.intents, "tools": tools})

    report = {
        "cases": len(cases),
        "passed": passed,
        "task_pass_rate": passed / len(cases) if cases else 0,
        "details": details,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
