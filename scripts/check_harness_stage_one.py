"""Validate the single machine proof for the mature Harness H2 baseline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import check_guard_wiring, check_h2_real_interop  # noqa: E402
from scripts.check_harness_acceptance import evaluate as evaluate_harness  # noqa: E402


PROOF = ROOT / "docs/decisions/148/harness-stage-one-proof.json"
HARNESS = ROOT / "data/harness_acceptance.json"
PAIRWISE = ROOT / "docs/decisions/146/orchestration-h2-proof.json"
EXPECTED = {
    "registered_h2_technologies": 12,
    "h2_ready_technologies": 12,
    "pairwise_state_coverage": 1.0,
    "real_interop_passed": 1,
    "postgres_service_tests": 4,
    "qdrant_service_tests": 4,
    "configured_service_skips": 0,
    "unregistered_test_skips": 0,
    "guards": 50,
    "unwired_guards": 0,
    "full_gate_passed": 1,
    "tracked_files_unchanged": 1,
}


def evaluate(proof: Any) -> list[str]:
    if not isinstance(proof, dict):
        return ["stage-one proof must be an object"]
    failures: list[str] = []
    if proof.get("round") != 148 or proof.get("status") != "passed":
        failures.append("stage-one proof must be the passed R148 result")
    metrics = proof.get("metrics")
    if not isinstance(metrics, dict):
        return [*failures, "metrics must be an object"]
    for name, target in EXPECTED.items():
        if metrics.get(name) != target:
            failures.append(f"{name}: expected {target}, got {metrics.get(name)!r}")

    harness = json.loads(HARNESS.read_text(encoding="utf-8"))
    failures.extend(f"harness: {item}" for item in evaluate_harness(harness, horizon=148))
    technologies = harness.get("technologies", {})
    ready = sum(
        isinstance(entry, dict) and entry.get("status") == "h2_ready"
        for entry in technologies.values()
    )
    if len(technologies) != metrics.get("registered_h2_technologies"):
        failures.append("published registered technology count drifted")
    if ready != metrics.get("h2_ready_technologies"):
        failures.append("published H2-ready technology count drifted")

    pairwise = json.loads(PAIRWISE.read_text(encoding="utf-8"))
    if pairwise.get("metrics", {}).get("pairwise_state_coverage") != metrics.get(
        "pairwise_state_coverage"
    ):
        failures.append("published pairwise coverage drifted")
    interop = json.loads(check_h2_real_interop.PROOF.read_text(encoding="utf-8"))
    if check_h2_real_interop.evaluate(interop):
        failures.append("H23 real-interoperability proof is no longer valid")

    guards, surfaces, imports = check_guard_wiring.collect()
    wiring_failures = check_guard_wiring.evaluate(guards, surfaces, imports)
    if len(guards) != metrics.get("guards"):
        failures.append("published guard count drifted")
    if len(wiring_failures) != metrics.get("unwired_guards"):
        failures.append("published guard wiring result drifted")

    service_evidence = proof.get("service_evidence")
    expected_jobs = {
        "postgres-storage": "postgres:16",
        "qdrant-vector-index": "qdrant/qdrant:v1.12.4",
    }
    if not isinstance(service_evidence, list) or len(service_evidence) != 2:
        failures.append("exactly two service evidence records are required")
    else:
        observed_jobs: dict[str, str] = {}
        for item in service_evidence:
            if not isinstance(item, dict):
                continue
            job = item.get("job")
            image = item.get("image")
            digest = item.get("sha256")
            if isinstance(job, str) and isinstance(image, str):
                observed_jobs[job] = image
            if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
                failures.append(f"service job {job!r} has no SHA-256 evidence")
        if observed_jobs != expected_jobs:
            failures.append("service job image set drifted")

    boundaries = proof.get("boundaries")
    if not isinstance(boundaries, dict):
        failures.append("stage-one boundaries must be declared")
    else:
        if boundaries.get("finance_quality_claim") is not False:
            failures.append("stage one may not claim finance effectiveness")
        if boundaries.get("second_domain_added") is not False:
            failures.append("stage one may not add a second product domain")
        if boundaries.get("graph_runtime") != "LangGraph":
            failures.append("LangGraph must remain the sole graph runtime")
    return failures


def _self_test(proof: dict[str, Any]) -> None:
    if evaluate(proof):
        raise SystemExit("harness_stage_one_self_test=FAIL published proof is dirty")
    metrics = proof["metrics"]
    cases = {
        "missing_technology": {
            **proof,
            "metrics": {**metrics, "h2_ready_technologies": 11},
        },
        "pairwise_gap": {
            **proof,
            "metrics": {**metrics, "pairwise_state_coverage": 0.99},
        },
        "postgres_skip": {
            **proof,
            "metrics": {**metrics, "configured_service_skips": 1},
        },
        "unwired_guard": {**proof, "metrics": {**metrics, "unwired_guards": 1}},
        "tracked_mutation": {
            **proof,
            "metrics": {**metrics, "tracked_files_unchanged": 0},
        },
        "quality_overclaim": {
            **proof,
            "boundaries": {**proof["boundaries"], "finance_quality_claim": True},
        },
    }
    for label, broken in cases.items():
        if not evaluate(broken):
            raise SystemExit(f"harness_stage_one_self_test=FAIL accepted {label}")
    print(f"harness_stage_one_self_test=PASS cases={len(cases) + 1}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
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
