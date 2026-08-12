"""Validate the complete failed R160 product candidate without overclaiming it."""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PROOF = ROOT / "docs/decisions/160/failed-product-candidate.json"
EXPECTED_IDS = [f"Q{index:02d}" for index in range(1, 31)]
EXPECTED_FIDELITY = {
    "llm": "live",
    "retrieval": "live",
    "structured_data": "live",
}
SHA256 = re.compile(r"[0-9a-f]{64}")


def evaluate(proof: Any) -> list[str]:
    if not isinstance(proof, dict):
        return ["proof must be an object"]
    failures: list[str] = []
    if proof.get("schema_version") != "f14-failed-product-candidate-v1":
        failures.append("schema_version must identify the R160 failed candidate")
    if proof.get("round") != 160 or proof.get("task") != "F14":
        failures.append("proof must describe R160 F14")
    if proof.get("status") != "product_acceptance_failed":
        failures.append("R160 must preserve the observed product acceptance failure")
    if proof.get("preregistration") != "docs/decisions/160/preregistration.json":
        failures.append("proof must point to the R160 preregistration")
    source = proof.get("source")
    if not isinstance(source, dict) or source.get("artifact") != "artifacts/160/product-candidate.json":
        failures.append("source must identify the exact-once merged candidate")
    elif SHA256.fullmatch(str(source.get("sha256", ""))) is None:
        failures.append("source must have a SHA-256 digest")

    execution = proof.get("execution")
    if not isinstance(execution, dict):
        return [*failures, "execution must be an object"]
    expected_execution = {
        "commit": "a487a75",
        "generation": "r160-f14",
        "coverage": "30/30",
        "done": 30,
        "errors": 0,
        "provider_fidelity": EXPECTED_FIDELITY,
        "saved_states": False,
        "rerun_or_best_of": False,
        "cross_run_splicing": False,
    }
    for name, expected in expected_execution.items():
        if execution.get(name) != expected:
            failures.append(f"execution.{name}: expected {expected!r}, got {execution.get(name)!r}")
    if execution.get("question_ids") != EXPECTED_IDS:
        failures.append("execution.question_ids must be the exact ordered Q01-Q30 cohort")

    metrics = proof.get("metrics")
    if not isinstance(metrics, dict):
        return [*failures, "metrics must be an object"]
    evidence = metrics.get("extracted_evidence")
    reachable = metrics.get("reader_visible_evidence")
    if evidence != 3089 or reachable != 2333:
        failures.append("evidence funnel must preserve the observed 2333/3089 counts")
    recomputed = reachable / evidence if isinstance(evidence, int) and evidence else 0.0
    if abs(float(metrics.get("evidence_reachable_rate", -1)) - recomputed) > 1e-12:
        failures.append("evidence_reachable_rate does not recompute from the funnel")
    if recomputed < 0.60:
        failures.append("R160 unexpectedly misses the evidence-reachable threshold")
    if metrics.get("orphaned_sub_questions") != 0:
        failures.append("R160 must preserve zero orphaned sub-questions")
    if metrics.get("false_premise_failed") != 1:
        failures.append("R160 must preserve one false-premise failure")
    if metrics.get("false_premise_failed_ids") != ["Q16"]:
        failures.append("Q16 must remain the sole false-premise failure")
    total = float(metrics.get("generation_cost_cny", -1)) + float(
        metrics.get("judge_cost_cny", -1)
    )
    if abs(total - float(metrics.get("total_cost_cny", -1))) > 1e-8:
        failures.append("total cost does not recompute")
    if not 0 <= total <= float(metrics.get("round_fuse_cny", -1)) == 48.0:
        failures.append("R160 total cost must remain within the CNY 48 fuse")

    failure = proof.get("failure")
    if not isinstance(failure, dict):
        failures.append("failure must identify the routed defect class")
    else:
        if failure.get("class") != "reporter_adopts_false_premise_despite_contradicting_evidence":
            failures.append("failure class must preserve the Q16 Reporter defect")
        if failure.get("route") != "conditional_F13":
            failures.append("the failed candidate must route to conditional F13")
        for locator in ("q16_report", "q16_state"):
            value = failure.get(locator)
            if not isinstance(value, dict) or SHA256.fullmatch(str(value.get("sha256", ""))) is None:
                failures.append(f"failure.{locator} must have an artifact hash")

    boundaries = proof.get("boundaries")
    expected_boundaries = {
        "qualifies_as_product_proof": False,
        "may_be_spliced_into_later_candidate": False,
        "tavily_key_replaced": False,
        "paid_provider_calls_after_completion": False,
    }
    if not isinstance(boundaries, dict):
        failures.append("boundaries must be an object")
    else:
        for name, expected in expected_boundaries.items():
            if boundaries.get(name) is not expected:
                failures.append(f"boundaries.{name} must be {expected}")
    return failures


def _self_test(proof: dict[str, Any]) -> None:
    if evaluate(proof):
        raise SystemExit("f14_failed_candidate_self_test=FAIL published proof is not clean")
    hidden = copy.deepcopy(proof)
    hidden["metrics"]["false_premise_failed"] = 0
    overclaim = copy.deepcopy(proof)
    overclaim["boundaries"]["qualifies_as_product_proof"] = True
    cases = {"hide_q16_failure": hidden, "product_overclaim": overclaim}
    missed = [name for name, candidate in cases.items() if not evaluate(candidate)]
    if missed:
        raise SystemExit(f"f14_failed_candidate_self_test=FAIL missed={missed}")
    print(f"f14_failed_candidate_self_test=PASS cases={len(cases)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    proof = json.loads(PROOF.read_text(encoding="utf-8"))
    if args.self_test:
        _self_test(proof)
    failures = evaluate(proof)
    for failure in failures:
        print(f"f14_failed_candidate_error: {failure}", file=sys.stderr)
    print(f"f14_failed_candidate={'PASS' if not failures else 'FAIL'} failures={len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
