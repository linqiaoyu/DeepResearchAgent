"""Freeze the cost-aware stage-two execution contract."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "data/stage_two_execution.json"
EXPECTED = {
    "version": 1,
    "target_round": 160,
    "f01": {
        "purpose": "live_loss_diagnostic",
        "recovery_full_runs": 0,
        "formal_product_metrics": False,
        "failed_case_reruns": 0,
    },
    "f11": {
        "purpose": "live_reliability_canary",
        "minimum_cases": 6,
        "maximum_cases": 10,
        "formal_product_metrics": False,
        "may_contribute_to_f14": False,
    },
    "f13": {
        "trigger": "failed_full_product_acceptance_only",
        "scheduled_full_runs": 0,
    },
    "f14": {
        "purpose": "full_product_acceptance",
        "planned_full_runs": 1,
        "questions": 30,
        "provider_fidelity": {
            "llm": "live",
            "retrieval": "live",
            "structured_data": "live",
        },
        "saved_states": False,
        "best_of": False,
        "cross_run_splicing": False,
    },
    "f15": {"paid_provider_calls": 0},
}


def evaluate(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return ["stage-two execution registry must be an object"]
    failures: list[str] = []
    for key, expected in EXPECTED.items():
        if payload.get(key) != expected:
            failures.append(f"{key}: expected {expected!r}, got {payload.get(key)!r}")
    if set(payload) != set(EXPECTED):
        failures.append("registry may not add an undeclared execution path")
    return failures


def _self_test(payload: dict[str, Any]) -> None:
    if evaluate(payload):
        raise SystemExit("stage_two_execution_self_test=FAIL registry is dirty")
    cases = {
        "f01_recovery": {
            **payload,
            "f01": {**payload["f01"], "recovery_full_runs": 1},
        },
        "f11_full_cohort": {
            **payload,
            "f11": {**payload["f11"], "maximum_cases": 30},
        },
        "routine_f13": {
            **payload,
            "f13": {**payload["f13"], "scheduled_full_runs": 1},
        },
        "spliced_f14": {
            **payload,
            "f14": {**payload["f14"], "cross_run_splicing": True},
        },
        "paid_f15": {
            **payload,
            "f15": {"paid_provider_calls": 1},
        },
    }
    for label, broken in cases.items():
        if not evaluate(broken):
            raise SystemExit(f"stage_two_execution_self_test=FAIL accepted {label}")
    print(f"stage_two_execution_self_test=PASS cases={len(cases) + 1}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    if args.self_test:
        _self_test(payload)
    failures = evaluate(payload)
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print("stage_two_execution=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
