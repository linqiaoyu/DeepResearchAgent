"""Validate one-to-one plan criterion accounting for an implementation round."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


TERMINAL_STATUSES = {"PASS", "FAIL", "DEFERRED"}


def _load_list(path: Path, label: str) -> list[dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise ValueError(f"{label} must be a JSON list of objects")
    return payload


def validate(plan_path: Path, ledger_path: Path) -> None:
    plan = _load_list(plan_path, "plan")
    ledger = _load_list(ledger_path, "ledger")
    plan_refs = [item.get("plan_ref") for item in plan]
    if not all(isinstance(ref, str) and ref for ref in plan_refs):
        raise ValueError("every plan item requires plan_ref")
    if len(set(plan_refs)) != len(plan_refs):
        raise ValueError("plan_ref values must be unique")

    ledger_refs = [item.get("plan_ref") for item in ledger]
    if not all(isinstance(ref, str) and ref for ref in ledger_refs):
        raise ValueError("every ledger entry requires plan_ref")
    if len(set(ledger_refs)) != len(ledger_refs):
        raise ValueError("each plan_ref requires exactly one ledger entry")
    unknown = sorted(set(ledger_refs) - set(plan_refs))
    missing = sorted(set(plan_refs) - set(ledger_refs))
    if unknown or missing:
        raise ValueError(f"unknown_refs={unknown} missing_refs={missing}")

    for item in ledger:
        status = item.get("status")
        if status not in TERMINAL_STATUSES:
            raise ValueError(f"invalid terminal status for {item['plan_ref']}: {status!r}")
        if status == "DEFERRED" and not isinstance(item.get("reason"), str):
            raise ValueError(f"DEFERRED criterion requires a reason: {item['plan_ref']}")
        if status != "DEFERRED" and "reason" in item:
            raise ValueError(f"only DEFERRED criterion may carry a reason: {item['plan_ref']}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("plan", type=Path)
    parser.add_argument("ledger", type=Path)
    args = parser.parse_args()
    validate(args.plan, args.ledger)
    print("plan_coverage=100 duplicate_refs=0 missing_refs=0")


if __name__ == "__main__":
    main()
