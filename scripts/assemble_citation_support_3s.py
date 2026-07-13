"""Assemble bounded citation-support batches into the v1.1 release asset."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def main() -> None:
    args = _parse_args()
    batches = [_read_json(Path(path)) for path in args.inputs]
    baseline = _read_json(Path(args.baseline))
    expected_ids = [item["id"] for item in baseline["results"]]
    latest_by_id = {
        item["id"]: item for batch in batches for item in batch["results"]
    }
    results = [latest_by_id[qid] for qid in expected_ids if qid in latest_by_id]
    actual_ids = [item["id"] for item in results]
    if actual_ids != expected_ids:
        raise SystemExit(f"batch result ids do not match G3 release ids: {actual_ids}")
    if any(batch["verifier"]["samples_per_question"] != 3 for batch in batches):
        raise SystemExit("all batches must use three citation-support samples")
    rates = [float(item["support_rate"]) for item in results]
    baseline_by_id = {item["id"]: item for item in baseline["results"]}
    ledgers = [Path(path) for path in args.ledgers]
    payload = {
        "version": "v1.1",
        "generation": "G3",
        "retrieval_corpus_as_of": _retrieval_as_of(Path(args.freeze)),
        "verifier": {
            "model": "qwen3.7-plus",
            "samples_per_question": 3,
            "aggregation": "per-claim majority vote; three-way ties use ordinal median (supported=1, partially_supported=0.5, unsupported=0)",
        },
        "effective_question_ids": expected_ids,
        "results": results,
        "summary": {
            "cases": len(results),
            "avg_citation_support_rate": round(sum(rates) / len(rates), 4),
            "single_sample_avg_citation_support_rate": baseline["summary"]["avg_citation_support_rate"],
            "difference_vs_single_sample": round(
                (sum(rates) / len(rates)) - baseline["summary"]["avg_citation_support_rate"], 4
            ),
            "per_question_differences": {
                item["id"]: round(
                    item["support_rate"] - baseline_by_id[item["id"]]["citation_support"]["support_rate"],
                    3,
                )
                for item in results
            },
        },
        "cost": {
            "batch_ledgers": [str(path) for path in ledgers],
            "calls": sum(_ledger_calls(path) for path in ledgers),
            "cost_cny": round(sum(_ledger_cost(path) for path in ledgers), 8),
            "budget_cny": args.budget_cny,
        },
    }
    output = Path(args.output)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"assembled {output}")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _retrieval_as_of(freeze: Path) -> str:
    match = re.search(
        r"^retrieval_corpus_as_of:\s*(\d{4}-\d{2}-\d{2})$",
        freeze.read_text(encoding="utf-8"),
        flags=re.MULTILINE,
    )
    if not match:
        raise SystemExit("freeze note does not declare retrieval_corpus_as_of")
    return match.group(1)


def _ledger_calls(path: Path) -> int:
    return len([line for line in path.read_text(encoding="utf-8").splitlines() if line])


def _ledger_cost(path: Path) -> float:
    return sum(float(json.loads(line).get("cost_cny", 0.0)) for line in path.read_text(encoding="utf-8").splitlines() if line)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", nargs="+", required=True)
    parser.add_argument("--ledgers", nargs="+", required=True)
    parser.add_argument("--baseline", default="data/golden_set/v1/results/g3_judge_v11.json")
    parser.add_argument("--freeze", default="data/golden_set/v1/freeze.md")
    parser.add_argument("--output", default="data/golden_set/v1/results/g3_citation_support_3s.json")
    parser.add_argument("--budget-cny", type=float, default=2.0)
    return parser.parse_args()


if __name__ == "__main__":
    main()
