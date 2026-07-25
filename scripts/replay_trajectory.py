from __future__ import annotations

import argparse
import json
from pathlib import Path

from deepresearch_agent.trajectory import load_trajectory
from deepresearch_agent.trajectory_replay import replay_trajectory


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replay a recorded AgentTrajectory without provider calls."
    )
    parser.add_argument("trajectory")
    parser.add_argument(
        "--require-call",
        action="append",
        default=[],
        help="Required recorded call such as tool:web_search or llm:reporter.",
    )
    args = parser.parse_args()

    trajectory = load_trajectory(Path(args.trajectory))
    result = replay_trajectory(
        trajectory,
        mode="strict",
        required_calls=args.require_call,
    )
    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
    if result.status == "cache_miss":
        raise SystemExit(3)
    if result.status == "mismatch":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
