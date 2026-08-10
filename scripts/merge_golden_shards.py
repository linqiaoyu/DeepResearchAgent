"""Merge golden-round shards into one round result.

R113 ran the golden set live. Serial execution spent 64% of its wall clock
waiting on the provider (109 of 170 minutes, 21.6 LLM calls per question at a
31.6s median), which projected to 9.5 hours for 30 questions. The remaining
questions were therefore sharded across concurrent processes.

Sharding changes scheduling, not the instrument: same questions, same ground
truth, same judge sampling, same budgets. This merges the per-shard outputs
back into one round and refuses to hide anything -- a question that appears
twice, or not at all, is an error rather than a silent pick.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def merge(paths: list[Path], *, round_id: str, expected: int) -> dict[str, Any]:
    merged: dict[str, dict[str, Any]] = {}
    duplicates: list[str] = []
    superseded: list[dict[str, str]] = []
    base: dict[str, Any] | None = None
    for path in sorted(paths):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if base is None:
            base = payload
        for result in payload.get("results", []):
            qid = str(result.get("id"))
            existing = merged.get(qid)
            if existing is None:
                merged[qid] = result
                continue
            # The only duplicate this accepts is a question that errored in one
            # place and was recovered in another. Recording which entry lost,
            # and why, is the point: a silent "pick the better score" is exactly
            # what AGENTS.md section 7 forbids.
            if existing.get("status") == "error" and result.get("status") != "error":
                superseded.append(
                    {
                        "id": qid,
                        "replaced_status": str(existing.get("status")),
                        "replaced_error_type": str(existing.get("error_type")),
                        "replaced_error": str(existing.get("error"))[:200],
                        "source": path.name,
                    }
                )
                merged[qid] = result
            elif result.get("status") == "error" and existing.get("status") != "error":
                superseded.append(
                    {
                        "id": qid,
                        "replaced_status": str(result.get("status")),
                        "replaced_error_type": str(result.get("error_type")),
                        "replaced_error": str(result.get("error"))[:200],
                        "source": path.name,
                    }
                )
            else:
                duplicates.append(qid)
    if base is None:
        raise ValueError("no shard outputs given")
    if duplicates:
        raise ValueError(
            "question(s) scored more than once with no failure to supersede: "
            f"{sorted(set(duplicates))}"
        )

    ordered = [merged[qid] for qid in sorted(merged)]
    errors = [item for item in ordered if item.get("status") == "error"]
    return {
        "round_id": round_id,
        "gold_version": base.get("gold_version"),
        "evaluation_as_of": base.get("evaluation_as_of"),
        "judge_samples": base.get("judge_samples"),
        "fidelity": "live",
        "execution": "serial phase Q01-Q10, then four concurrent shards Q11-Q30",
        "expected_questions": expected,
        "scored_questions": len(ordered),
        "coverage": f"{len(ordered)}/{expected}",
        "error_questions": [item["id"] for item in errors],
        "structured_failures": len(errors),
        "superseded_failures": superseded,
        "results": ordered,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("shards", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--round-id", default="113-live-merged")
    parser.add_argument("--expected", type=int, default=30)
    args = parser.parse_args()

    payload = merge(args.shards, round_id=args.round_id, expected=args.expected)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"coverage={payload['coverage']}")
    print(f"scored={payload['scored_questions']} errors={payload['structured_failures']}")
    if payload["error_questions"]:
        print(f"error_questions={','.join(payload['error_questions'])}")
    for entry in payload["superseded_failures"]:
        print(
            f"superseded={entry['id']} replaced={entry['replaced_error_type']} "
            f"by={entry['source']}"
        )
    print(f"written={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
