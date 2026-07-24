from __future__ import annotations

import argparse
import json
from pathlib import Path

from deepresearch_agent.evaluation.offline import compare_result_payloads


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only metric delta comparison.")
    parser.add_argument("left")
    parser.add_argument("right")
    parser.add_argument("--band", type=float, default=0.01)
    args = parser.parse_args()
    left = json.loads(Path(args.left).read_text(encoding="utf-8"))
    right = json.loads(Path(args.right).read_text(encoding="utf-8"))
    rows = compare_result_payloads(left, right, significance_band=args.band)
    print(json.dumps([row.model_dump(mode="json") for row in rows], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
