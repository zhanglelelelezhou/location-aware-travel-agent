import argparse
import json
from pathlib import Path
from typing import Any


def load_report(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def percentage(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare two travel-agent evaluation reports.")
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    args = parser.parse_args()

    baseline = load_report(args.baseline)
    candidate = load_report(args.candidate)
    metrics = [
        ("Task pass rate", "task_pass_rate"),
        ("Intent accuracy", "intent_accuracy"),
        ("Tool accuracy", "tool_accuracy"),
        ("Constraint accuracy", "constraint_accuracy"),
    ]

    print("| Metric | Baseline | Candidate | Delta |")
    print("| --- | ---: | ---: | ---: |")
    for label, key in metrics:
        before = baseline.get(key)
        after = candidate.get(key)
        delta = None if before is None or after is None else after - before
        delta_text = "n/a" if delta is None else f"{delta * 100:+.1f} pp"
        print(f"| {label} | {percentage(before)} | {percentage(after)} | {delta_text} |")

    baseline_p95 = baseline.get("end_to_end_latency_ms", {}).get("p95", 0)
    candidate_p95 = candidate.get("end_to_end_latency_ms", {}).get("p95", 0)
    print(f"\nEnd-to-end P95 latency: {baseline_p95} ms -> {candidate_p95} ms")
    print(
        "Estimated candidate cost: "
        f"${candidate.get('usage', {}).get('estimated_cost_usd', 0):.6f}"
    )
    print(f"Fallbacks: {candidate.get('fallback_count', 0)}")
    print(f"Repairs: {candidate.get('repair_count', 0)}")


if __name__ == "__main__":
    main()
