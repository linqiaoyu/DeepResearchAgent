from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from deepresearch_agent.evaluation import aggregate_round_results


def main() -> None:
    args = _parse_args()
    question_payload = json.loads(Path(args.questions).read_text(encoding="utf-8"))
    quarantined = set(question_payload.get("meta", {}).get("quarantined_question_ids", []))
    expected_ids = [
        str(item["id"])
        for item in question_payload.get("questions", [])
        if str(item["id"]) not in quarantined and item.get("freeze_status") != "quarantine"
    ]
    by_id: dict[str, dict[str, Any]] = {}
    source_rounds: list[str] = []
    for input_path in args.inputs:
        payload = json.loads(Path(input_path).read_text(encoding="utf-8"))
        source_rounds.append(str(payload.get("round_id", input_path)))
        for result in payload.get("results", []):
            qid = str(result["id"])
            if qid in by_id:
                raise ValueError(f"duplicate result while combining: {qid}")
            by_id[qid] = result
    missing = [qid for qid in expected_ids if qid not in by_id]
    extra = sorted(set(by_id) - set(expected_ids))
    if missing or extra:
        raise ValueError(f"combined result mismatch: missing={missing}, extra={extra}")

    results = [by_id[qid] for qid in expected_ids]
    for order, result in enumerate(results, 1):
        result["order"] = order
    structured_failures = sum(result.get("status") != "done" for result in results)
    summary = aggregate_round_results(results)
    summary["total_judge_cost_cny"] = round(
        sum(float(item.get("judge_cost_cny", 0.0)) for item in results),
        8,
    )
    payload = {
        "round_id": args.round_id,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "generation": args.generation,
        "gold_version": question_payload.get("meta", {}).get("version"),
        "evaluation_as_of": args.as_of,
        "judge_samples": args.judge_samples,
        "effective_question_ids": expected_ids,
        "quarantined_question_ids": sorted(quarantined),
        "combined_from": source_rounds,
        "structured_failures": structured_failures,
        "structured_failure_rate": round(structured_failures / len(results), 4),
        "results": results,
        "summary": summary,
    }
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Combine disjoint Golden judge shards.")
    parser.add_argument("--questions", default="data/golden_set/v1/questions.json")
    parser.add_argument("--inputs", nargs="+", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--round-id", required=True)
    parser.add_argument("--generation", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--judge-samples", type=int, default=3)
    return parser.parse_args()


if __name__ == "__main__":
    main()
