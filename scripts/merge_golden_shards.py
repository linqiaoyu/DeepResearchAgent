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


def merge(
    paths: list[Path],
    *,
    round_id: str,
    expected: int,
    allow_failed_supersession: bool = False,
) -> dict[str, Any]:
    merged: dict[str, dict[str, Any]] = {}
    duplicates: list[str] = []
    superseded: list[dict[str, str]] = []
    base: dict[str, Any] | None = None
    metadata_fields = (
        "generation",
        "gold_version",
        "evaluation_as_of",
        "judge_samples",
        "state_path_map",
        "provider_fidelity",
    )
    for path in sorted(paths):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if base is None:
            base = payload
        else:
            drift = {
                field: (base.get(field), payload.get(field))
                for field in metadata_fields
                if base.get(field) != payload.get(field)
            }
            if drift:
                raise ValueError(f"shard metadata mismatch in {path.name}: {drift}")
        for result in payload.get("results", []):
            qid = str(result.get("id"))
            existing = merged.get(qid)
            if existing is None:
                merged[qid] = result
                continue
            # Historical rounds recovered some failed cases in later shards.
            # Fresh experiments default to exact-once and must explicitly opt
            # into that legacy merge policy so a rerun cannot become best-of.
            if not allow_failed_supersession:
                duplicates.append(qid)
            elif existing.get("status") == "error" and result.get("status") != "error":
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
        "generation": base.get("generation"),
        "provider_fidelity": base.get("provider_fidelity"),
        "state_path_map": base.get("state_path_map"),
        "fidelity": "live",
        "execution": (
            "merged shards with legacy failed-case supersession"
            if allow_failed_supersession
            else "merged exact-once shards"
        ),
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
    parser.add_argument(
        "--allow-failed-supersession",
        action="store_true",
        help="legacy policy: replace an errored duplicate with a completed duplicate",
    )
    args = parser.parse_args()

    payload = merge(
        args.shards,
        round_id=args.round_id,
        expected=args.expected,
        allow_failed_supersession=args.allow_failed_supersession,
    )
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
