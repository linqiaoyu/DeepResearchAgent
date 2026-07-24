from __future__ import annotations

import argparse
import json
from pathlib import Path

from deepresearch_agent.evaluation.offline import validate_golden_schema


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only Golden schema validator.")
    parser.add_argument("--questions", default="data/golden_set/v1/questions.json")
    parser.add_argument("--revisions", default="data/golden_set/v1/revisions_v11.json")
    args = parser.parse_args()
    questions = json.loads(Path(args.questions).read_text(encoding="utf-8"))
    revisions = json.loads(Path(args.revisions).read_text(encoding="utf-8"))
    issues = validate_golden_schema(questions, revisions)
    print(json.dumps({"valid": not issues, "issues": issues}, ensure_ascii=False, indent=2))
    if issues:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
