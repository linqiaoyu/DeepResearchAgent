from __future__ import annotations

import argparse
import json
from pathlib import Path

from deepresearch_agent.provenance import RunManifest, compare_manifests


def main() -> None:
    parser = argparse.ArgumentParser(description="Check whether two run manifests are comparable.")
    parser.add_argument("left")
    parser.add_argument("right")
    args = parser.parse_args()
    left = RunManifest.model_validate_json(Path(args.left).read_text(encoding="utf-8"))
    right = RunManifest.model_validate_json(Path(args.right).read_text(encoding="utf-8"))
    comparison = compare_manifests(left, right)
    print(json.dumps(comparison.model_dump(mode="json"), ensure_ascii=False, indent=2))
    if not comparison.comparable:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
