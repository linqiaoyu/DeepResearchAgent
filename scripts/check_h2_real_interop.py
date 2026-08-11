"""Validate the published H23 real-boundary interoperability proof."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PROOF = ROOT / "docs/decisions/147/real-interop-proof.json"
EXPECTED_MINIMUMS = {
    "real_llm_successes": 3,
    "real_rag_successes": 3,
    "real_mcp_successes": 3,
    "llm_failure_degradations": 1,
    "rag_failure_degradations": 1,
    "mcp_failure_degradations": 1,
    "observability_coverage": 1.0,
    "observed_probes": 12,
}


def evaluate(proof: Any) -> list[str]:
    if not isinstance(proof, dict):
        return ["proof must be an object"]
    failures: list[str] = []
    if proof.get("round") != 147 or proof.get("status") != "passed":
        failures.append("proof must be the passed R147 result")
    preregistration = proof.get("preregistration")
    if (
        not isinstance(preregistration, str)
        or preregistration != "docs/decisions/147/preregistration.json"
        or not (ROOT / preregistration).is_file()
    ):
        failures.append("published preregistration is missing")
    metrics = proof.get("metrics")
    if not isinstance(metrics, dict):
        return [*failures, "metrics must be an object"]
    for name, target in EXPECTED_MINIMUMS.items():
        value = metrics.get(name)
        if not isinstance(value, int | float) or value < target:
            failures.append(f"{name} must be >= {target}, got {value!r}")
    cost = metrics.get("total_cost_cny")
    fuse = metrics.get("round_fuse_cny")
    if (
        not isinstance(cost, int | float)
        or not isinstance(fuse, int | float)
        or fuse != 40.0
        or cost < 0
        or cost > fuse
    ):
        failures.append("total_cost_cny must be within the fixed CNY 40 fuse")
    sources = proof.get("sources")
    if not isinstance(sources, list) or len(sources) != 6:
        failures.append("proof must identify exactly six source artifacts")
    else:
        for index, source in enumerate(sources):
            if not isinstance(source, dict):
                failures.append(f"source #{index} must be an object")
                continue
            artifact = source.get("artifact")
            digest = source.get("sha256")
            if not isinstance(artifact, str) or not artifact.startswith("artifacts/147/"):
                failures.append(f"source #{index} is outside artifacts/147")
            if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
                failures.append(f"source #{index} has no SHA-256 digest")
    notes = proof.get("notes")
    if not isinstance(notes, dict):
        failures.append("notes must be an object")
    else:
        if notes.get("quality_claim") is not False:
            failures.append("H23 must not claim finance quality")
        if notes.get("remote_qdrant_mutated") is not False:
            failures.append("proof may not conceal a remote Qdrant write")
        if notes.get("rag_service") != "temporary local qdrant/qdrant:v1.18.3-unprivileged":
            failures.append("RAG service image must remain exactly pinned")
    return failures


def _self_test(proof: dict[str, Any]) -> None:
    if evaluate(proof):
        raise SystemExit("h2_real_interop_self_test=FAIL published proof is dirty")
    metrics = proof["metrics"]
    cases = {
        "fixture_llm": {**proof, "metrics": {**metrics, "real_llm_successes": 2}},
        "empty_rag": {**proof, "metrics": {**metrics, "real_rag_successes": 2}},
        "reused_mcp": {**proof, "metrics": {**metrics, "real_mcp_successes": 2}},
        "missing_degradation": {
            **proof,
            "metrics": {**metrics, "rag_failure_degradations": 0},
        },
        "missing_observability": {
            **proof,
            "metrics": {**metrics, "observability_coverage": 11 / 12},
        },
        "cost_overrun": {**proof, "metrics": {**metrics, "total_cost_cny": 40.01}},
        "quality_overclaim": {**proof, "notes": {**proof["notes"], "quality_claim": True}},
    }
    for label, broken in cases.items():
        if not evaluate(broken):
            raise SystemExit(f"h2_real_interop_self_test=FAIL accepted {label}")
    print(f"h2_real_interop_self_test=PASS cases={len(cases) + 1}")


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
