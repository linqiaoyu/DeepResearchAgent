"""Validate the published R149 targeted Harness reliability proof."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PROOF = ROOT / "docs/decisions/149/reliability-probe-proof.json"
PREREGISTRATION = "docs/decisions/149/reliability-probe-preregistration.json"


def evaluate(proof: Any) -> list[str]:
    if not isinstance(proof, dict):
        return ["proof must be an object"]
    failures: list[str] = []
    if proof.get("round") != 149 or proof.get("status") != "passed":
        failures.append("proof must be the passed R149 targeted reliability result")
    if proof.get("preregistration") != PREREGISTRATION or not (ROOT / PREREGISTRATION).is_file():
        failures.append("proof must point to the published preregistration")
    if proof.get("quality_claim") is not False or proof.get("golden_cases_rerun") != 0:
        failures.append("targeted probes may not claim quality or rerun golden cases")
    source = proof.get("source")
    if not isinstance(source, dict):
        failures.append("source must be an object")
    else:
        artifact = source.get("artifact")
        digest = source.get("sha256")
        if artifact != "artifacts/149/reliability/probe-results.json":
            failures.append("source must be the fixed R149 reliability artifact")
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            failures.append("source must carry a SHA-256 digest")
    metrics = proof.get("metrics")
    if not isinstance(metrics, dict):
        return [*failures, "metrics must be an object"]
    exact = {
        "ledger_processes": 4,
        "ledger_successes": 4,
        "distinct_ledger_authorities": 4,
        "distinct_ledger_indexes": 4,
        "planner_calls": 3,
        "planner_successes": 3,
        "planner_timeout_seconds": 180,
        "offline_verified_trajectories": 3,
    }
    for name, expected in exact.items():
        if metrics.get(name) != expected:
            failures.append(f"{name} must equal {expected}, got {metrics.get(name)!r}")
    if metrics.get("duplicate_authority_negative_control_rejected") is not True:
        failures.append("duplicate-authority negative control must be rejected")
    cost = metrics.get("planner_cost_cny")
    if not isinstance(cost, int | float) or cost < 0 or cost > 1.0:
        failures.append("planner cost must remain inside the preregistered CNY 1 fuse")
    return failures


def build_proof(source_path: Path) -> dict[str, Any]:
    source_path = source_path.resolve()
    raw = json.loads(source_path.read_text(encoding="utf-8"))
    ledger = raw["ledger"]
    planner = raw["planner"]
    return {
        "round": 149,
        "status": "passed",
        "preregistration": PREREGISTRATION,
        "quality_claim": False,
        "golden_cases_rerun": 0,
        "source": {
            "artifact": str(source_path.relative_to(ROOT)),
            "sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        },
        "metrics": {
            "ledger_processes": ledger["processes"],
            "ledger_successes": ledger["successes"],
            "distinct_ledger_authorities": ledger["distinct_authorities"],
            "distinct_ledger_indexes": ledger["distinct_indexes"],
            "duplicate_authority_negative_control_rejected": ledger[
                "duplicate_authority_negative_control_rejected"
            ],
            "planner_calls": planner["calls"],
            "planner_successes": planner["successes"],
            "planner_timeout_seconds": planner["configured_timeout_seconds"],
            "offline_verified_trajectories": sum(
                record["offline_verified"] for record in planner["records"]
            ),
            "planner_cost_cny": planner["total_cost_cny"],
        },
    }


def _self_test(proof: dict[str, Any]) -> None:
    if evaluate(proof):
        raise SystemExit("r149_reliability_self_test=FAIL published proof is dirty")
    metrics = proof["metrics"]
    mutations = {
        "shared_ledger": {**metrics, "distinct_ledger_authorities": 1},
        "collision": {**metrics, "ledger_successes": 3},
        "timeout_regression": {**metrics, "planner_timeout_seconds": 60},
        "planner_failure": {**metrics, "planner_successes": 2},
        "missing_trace": {**metrics, "offline_verified_trajectories": 2},
        "cost_overrun": {**metrics, "planner_cost_cny": 1.01},
    }
    for label, broken_metrics in mutations.items():
        if not evaluate({**proof, "metrics": broken_metrics}):
            raise SystemExit(f"r149_reliability_self_test=FAIL accepted {label}")
    if not evaluate({**proof, "quality_claim": True}):
        raise SystemExit("r149_reliability_self_test=FAIL accepted quality overclaim")
    print(f"r149_reliability_self_test=PASS cases={len(mutations) + 2}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--build-from", type=Path)
    args = parser.parse_args()
    if args.build_from is not None:
        proof = build_proof(args.build_from)
        PROOF.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    else:
        proof = json.loads(PROOF.read_text(encoding="utf-8"))
    if args.self_test:
        _self_test(proof)
    failures = evaluate(proof)
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print(json.dumps(proof["metrics"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
