from __future__ import annotations

import argparse
import json
from pathlib import Path

from deepresearch_agent.evaluation.offline import calculate_offline_metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute metrics from existing trace and ledger JSONL.")
    parser.add_argument("--trace", required=True)
    parser.add_argument("--ledger", required=True)
    args = parser.parse_args()
    trace = _jsonl(Path(args.trace))
    ledger = _jsonl(Path(args.ledger))
    metrics = calculate_offline_metrics(trace, ledger)
    print(metrics.model_dump_json(indent=2))


def _jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


if __name__ == "__main__":
    main()
