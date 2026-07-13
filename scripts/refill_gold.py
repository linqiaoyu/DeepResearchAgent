from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from deepresearch_agent.evaluation.gold_audit import MetricNormalizer, enforce_refill_gate


def apply_manifest(
    payload: dict[str, Any],
    manifest: dict[str, Any],
    normalizer: MetricNormalizer,
) -> dict[str, Any]:
    result = copy.deepcopy(payload)
    from_version = str(manifest.get("from_version", ""))
    if result.get("meta", {}).get("version") != from_version:
        raise ValueError(
            f"manifest expects {from_version}, got {result.get('meta', {}).get('version')}"
        )
    questions = {str(item["id"]): item for item in result.get("questions", [])}
    authorized = {_parse_slot_key(str(item)) for item in manifest.get("authorized_slots", [])}
    declared = {
        (str(item["question_id"]), int(item["slot"]))
        for item in manifest.get("changes", [])
    }
    if not authorized:
        raise ValueError("manifest must declare authorized_slots")
    if declared != authorized:
        raise ValueError("manifest changes must exactly match authorized_slots")
    seen: set[tuple[str, int]] = set()
    for change in manifest.get("changes", []):
        qid = str(change["question_id"])
        slot_index = int(change["slot"])
        key = (qid, slot_index)
        if key in seen:
            raise ValueError(f"duplicate manifest change: {qid}s{slot_index}")
        seen.add(key)
        question = questions[qid]
        slots = question["gold"]["must_include"]
        current = slots[slot_index - 1]
        if current.get("value") != change.get("old_value"):
            raise ValueError(f"stale old_value for {qid}s{slot_index}")
        new_fields = change.get("new_fields")
        if not isinstance(new_fields, dict):
            raise ValueError(f"{qid}s{slot_index} new_fields must be an object")
        if new_fields.get("value") != change.get("new_value"):
            raise ValueError(f"{qid}s{slot_index} new_value log does not match new_fields")
        candidate = copy.deepcopy(current)
        for field in change.get("remove_fields", []):
            candidate.pop(str(field), None)
        candidate.update(copy.deepcopy(new_fields))
        enforce_refill_gate(question, candidate, slot_index, normalizer)
        slots[slot_index - 1] = candidate

    if seen != declared:
        raise ValueError("manifest change set mismatch")
    _enforce_shared_fact_groups(questions, manifest)
    result["meta"].update(manifest.get("meta_updates", {}))
    return result


def _parse_slot_key(value: str) -> tuple[str, int]:
    qid, separator, slot = value.partition("s")
    if not separator or not qid or not slot.isdigit():
        raise ValueError(f"invalid authorized slot key: {value}")
    return qid, int(slot)


def _enforce_shared_fact_groups(
    questions: dict[str, dict[str, Any]],
    manifest: dict[str, Any],
) -> None:
    for group in manifest.get("shared_fact_groups", []):
        slots = [_parse_slot_key(str(item)) for item in group.get("slots", [])]
        fields = [str(item) for item in group.get("match_fields", ["value", "source_ref"])]
        if len(slots) < 2:
            raise ValueError("shared fact group requires at least two slots")
        candidates = [questions[qid]["gold"]["must_include"][slot - 1] for qid, slot in slots]
        for field in fields:
            values = [candidate.get(field) for candidate in candidates]
            if any(value != values[0] for value in values[1:]):
                keys = ", ".join(f"{qid}s{slot}" for qid, slot in slots)
                raise ValueError(f"shared fact group differs on {field}: {keys}")


def main() -> None:
    args = _parse_args()
    questions_path = Path(args.questions)
    payload = json.loads(questions_path.read_text(encoding="utf-8"))
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    normalizer = MetricNormalizer.from_path(Path(args.normalization))
    updated = apply_manifest(payload, manifest, normalizer)
    print(f"validated {len(manifest.get('changes', []))} gated changes")
    if args.write:
        questions_path.write_text(
            json.dumps(updated, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"wrote {questions_path}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply evidence-backed Golden refills through the audit gate.")
    parser.add_argument("--questions", default="data/golden_set/v1/questions.json")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--normalization", default="data/finance_metric_normalization.json")
    parser.add_argument("--write", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    main()
