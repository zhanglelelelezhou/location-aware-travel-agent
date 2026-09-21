import argparse
import json

from travel_agent.graph import run_agent
from travel_agent.models import TravelRequest


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the travel agent in mock mode.")
    parser.add_argument("text")
    parser.add_argument("--location")
    parser.add_argument("--preference", action="append", default=[])
    parser.add_argument("--target-language", default="ja")
    args = parser.parse_args()

    response = run_agent(
        TravelRequest(
            text=args.text,
            location=args.location,
            preferences=args.preference,
            target_language=args.target_language,
        )
    )
    print(json.dumps(response.model_dump(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

