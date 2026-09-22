import argparse
import json

from travel_agent.graph import run_agent
from travel_agent.models import TravelRequest
from travel_agent.planner import build_planner_from_env
from travel_agent.tools import build_tool_registry_from_env


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the travel agent from the command line.")
    parser.add_argument("text")
    parser.add_argument("--location")
    parser.add_argument("--latitude", type=float)
    parser.add_argument("--longitude", type=float)
    parser.add_argument("--preference", action="append", default=[])
    parser.add_argument("--target-language", default="ja")
    parser.add_argument("--planner", choices=["rule", "llm"], default="rule")
    parser.add_argument(
        "--tools",
        choices=["mock", "open-meteo", "open-data", "mcp"],
        default="mock",
    )
    args = parser.parse_args()

    response = run_agent(
        TravelRequest(
            text=args.text,
            location=args.location,
            latitude=args.latitude,
            longitude=args.longitude,
            preferences=args.preference,
            target_language=args.target_language,
        ),
        registry=build_tool_registry_from_env(args.tools),
        planner=build_planner_from_env(args.planner),
    )
    print(json.dumps(response.model_dump(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
