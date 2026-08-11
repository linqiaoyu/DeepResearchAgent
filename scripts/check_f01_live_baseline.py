"""Validate the published F01 full-cohort live loss baseline."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PROOF = ROOT / "docs/decisions/149/live-loss-baseline-proof.json"
PREREGISTRATION = "docs/decisions/149/preregistration.json"
EXPECTED_IDS = [f"Q{number:02d}" for number in range(1, 31)]
EXPECTED_FIDELITY = {
    "llm": "live",
    "retrieval": "live",
    "structured_data": "live",
}
FUNNEL_FIELDS = {
    "retrieved_sources",
    "extracted_evidence",
    "packed_evidence",
    "cited_evidence",
    "reader_visible_evidence",
}


def _ledger_cost(path: Path) -> float:
    total = 0.0
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            total += float(row.get("cost_cny", 0) or 0)
    return total


def build_proof(
    source_path: Path,
    *,
    ledger_paths: list[Path] | None = None,
) -> dict[str, Any]:
    """Reduce the ignored raw result to a reviewable, content-free proof."""

    payload = json.loads(source_path.read_text(encoding="utf-8"))
    raw_cases = payload.get("results")
    if not isinstance(raw_cases, list):
        raise ValueError("source results must be a list")
    cases: list[dict[str, Any]] = []
    total_evidence = 0
    total_reachable = 0
    total_orphans = 0
    total_false_premise_failed = 0
    total_cost = 0.0
    funnel_totals = {name: 0 for name in FUNNEL_FIELDS}
    for raw in raw_cases:
        if not isinstance(raw, dict):
            raise ValueError("every source result must be an object")
        mechanical = raw.get("mechanical")
        if not isinstance(mechanical, dict):
            mechanical = {}
        funnel = mechanical.get("evidence_funnel", raw.get("evidence_funnel", {}))
        if not isinstance(funnel, dict):
            funnel = {}
        normalized_funnel = {
            name: int(funnel.get(name, 0) or 0) for name in sorted(FUNNEL_FIELDS)
        }
        for name, value in normalized_funnel.items():
            funnel_totals[name] += value
        evidence = int(raw.get("evidence_count", 0) or 0)
        reachable = int(mechanical.get("evidence_reachable_by_reader", 0) or 0)
        orphans = int(mechanical.get("orphaned_sub_questions", 0) or 0)
        false_premise = int(raw.get("false_premise_failed") is True)
        total_evidence += evidence
        total_reachable += reachable
        total_orphans += orphans
        total_false_premise_failed += false_premise
        case_cost = float(raw.get("cost_cny", 0) or 0) + float(
            raw.get("judge_cost_cny", 0) or 0
        )
        total_cost += case_cost
        cases.append(
            {
                "id": str(raw.get("id")),
                "status": raw.get("status"),
                "provider_fidelity": raw.get("provider_fidelity"),
                "evidence_funnel": normalized_funnel,
                "orphaned_sub_questions": orphans,
                "false_premise_failed": bool(raw.get("false_premise_failed", False)),
                "cost_cny": round(case_cost, 8),
                "latency_seconds": float(raw.get("latency_seconds", 0) or 0),
                "error_type": raw.get("error_type"),
            }
        )
    cases.sort(key=lambda item: item["id"])
    completed = sum(item["status"] == "done" for item in cases)
    fidelity_counts = {
        name: sum(
            item.get("provider_fidelity", {}).get(name) == "live"
            for item in cases
            if item.get("status") == "done"
            and isinstance(item.get("provider_fidelity"), dict)
        )
        for name in EXPECTED_FIDELITY
    }
    source_bytes = source_path.read_bytes()
    ledger_sources = [
        {
            "artifact": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in ledger_paths or []
    ]
    measured_cost = (
        sum(_ledger_cost(path) for path in ledger_paths)
        if ledger_paths
        else total_cost
    )
    return {
        "round": 149,
        "status": (
            "diagnostic_complete"
            if len(cases) == 30
            and all(item["status"] in {"done", "error"} for item in cases)
            and payload.get("superseded_failures") == []
            else "diagnostic_incomplete"
        ),
        "product_acceptance_status": "incomplete" if completed < 30 else "candidate",
        "preregistration": PREREGISTRATION,
        "source": {
            "artifact": "artifacts/149/merged-result.json",
            "sha256": hashlib.sha256(source_bytes).hexdigest(),
        },
        "ledger_sources": ledger_sources,
        "metrics": {
            "question_count": len(cases),
            "terminal_questions": sum(
                item["status"] in {"done", "error"} for item in cases
            ),
            "completed_questions": completed,
            "error_questions": len(cases) - completed,
            "live_llm_questions": fidelity_counts["llm"],
            "live_retrieval_questions": fidelity_counts["retrieval"],
            "live_structured_data_questions": fidelity_counts["structured_data"],
            "evidence_reachable_rate": round(
                total_reachable / total_evidence if total_evidence else 0.0, 6
            ),
            "orphaned_sub_questions": total_orphans,
            "false_premise_failed": total_false_premise_failed,
            "diagnostic_metric_denominator_cases": completed,
            "total_cost_cny": round(measured_cost, 8),
            "round_fuse_cny": 30.0,
            "funnel_totals": funnel_totals,
        },
        "cases": cases,
        "boundaries": {
            "capability_effect_claim": False,
            "rerun_or_best_of": bool(payload.get("superseded_failures")),
            "golden_truth_changed": False,
            "formal_product_metrics": False,
            "f01_30_of_30_done": completed == 30,
        },
    }


def evaluate(proof: Any) -> list[str]:
    if not isinstance(proof, dict):
        return ["proof must be an object"]
    failures: list[str] = []
    if proof.get("round") != 149 or proof.get("status") != "diagnostic_complete":
        failures.append("proof must be the complete R149 diagnostic baseline")
    if proof.get("product_acceptance_status") != "incomplete":
        failures.append("R149 product acceptance must remain explicitly incomplete")
    if proof.get("preregistration") != PREREGISTRATION:
        failures.append("proof must point to the fixed R149 preregistration")
    elif not (ROOT / PREREGISTRATION).is_file():
        failures.append("R149 preregistration is missing")

    source = proof.get("source")
    if not isinstance(source, dict):
        failures.append("source must be an object")
    else:
        if source.get("artifact") != "artifacts/149/merged-result.json":
            failures.append("source must identify the single merged raw result")
        digest = source.get("sha256")
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            failures.append("source must have a SHA-256 digest")

    metrics = proof.get("metrics")
    if not isinstance(metrics, dict):
        return [*failures, "metrics must be an object"]
    exact = {
        "question_count": 30,
        "terminal_questions": 30,
    }
    for name, expected in exact.items():
        if metrics.get(name) != expected:
            failures.append(f"{name}: expected {expected}, got {metrics.get(name)!r}")
    completed = metrics.get("completed_questions")
    errors = metrics.get("error_questions")
    if (
        not isinstance(completed, int)
        or not isinstance(errors, int)
        or completed + errors != 30
        or errors < 1
    ):
        failures.append("R149 must expose its incomplete done/error denominator")
    if metrics.get("diagnostic_metric_denominator_cases") != completed:
        failures.append("diagnostic metric denominator must equal successful cases")
    for name in (
        "live_llm_questions",
        "live_retrieval_questions",
        "live_structured_data_questions",
    ):
        if metrics.get(name) != completed:
            failures.append(f"{name} must equal the successful-case denominator")
    cost = metrics.get("total_cost_cny")
    fuse = metrics.get("round_fuse_cny")
    if (
        not isinstance(cost, int | float)
        or not isinstance(fuse, int | float)
        or fuse != 30.0
        or cost < 0
        or cost > fuse
    ):
        failures.append("total cost must be within the preregistered CNY 30 fuse")
    for name in (
        "evidence_reachable_rate",
        "orphaned_sub_questions",
        "false_premise_failed",
    ):
        if not isinstance(metrics.get(name), int | float):
            failures.append(f"{name} must be numeric")

    cases = proof.get("cases")
    if not isinstance(cases, list) or len(cases) != 30:
        return [*failures, "cases must contain exactly 30 entries"]
    ids = [str(case.get("id")) for case in cases if isinstance(case, dict)]
    if ids != EXPECTED_IDS:
        failures.append("cases must be Q01-Q30 in order, exactly once")
    for case in cases:
        if not isinstance(case, dict):
            failures.append("every case must be an object")
            continue
        qid = case.get("id")
        if case.get("status") not in {"done", "error"}:
            failures.append(f"{qid}: status must be terminal")
        if case.get("status") == "done" and case.get("provider_fidelity") != EXPECTED_FIDELITY:
            failures.append(f"{qid}: provider fidelity is not live/live/live")
        funnel = case.get("evidence_funnel")
        if not isinstance(funnel, dict) or set(funnel) != FUNNEL_FIELDS:
            failures.append(f"{qid}: five-stage evidence funnel is incomplete")
        elif any(not isinstance(value, int) or value < 0 for value in funnel.values()):
            failures.append(f"{qid}: evidence funnel counts must be non-negative integers")

    valid_cases = [case for case in cases if isinstance(case, dict)]
    observed_completed = sum(case.get("status") == "done" for case in valid_cases)
    observed_errors = sum(case.get("status") == "error" for case in valid_cases)
    if completed != observed_completed or errors != observed_errors:
        failures.append("published done/error counts do not equal the case records")
    observed_funnels = {
        name: sum(
            int(case.get("evidence_funnel", {}).get(name, 0) or 0)
            for case in valid_cases
            if isinstance(case.get("evidence_funnel"), dict)
        )
        for name in FUNNEL_FIELDS
    }
    if metrics.get("funnel_totals") != observed_funnels:
        failures.append("published funnel totals do not equal the 30 case records")
    extracted = observed_funnels["extracted_evidence"]
    observed_rate = round(
        observed_funnels["reader_visible_evidence"] / extracted if extracted else 0.0,
        6,
    )
    if metrics.get("evidence_reachable_rate") != observed_rate:
        failures.append("published evidence_reachable_rate does not recompute")
    observed_orphans = sum(
        int(case.get("orphaned_sub_questions", 0) or 0) for case in valid_cases
    )
    if metrics.get("orphaned_sub_questions") != observed_orphans:
        failures.append("published orphaned_sub_questions does not recompute")
    observed_false_premise = sum(
        case.get("false_premise_failed") is True for case in valid_cases
    )
    if metrics.get("false_premise_failed") != observed_false_premise:
        failures.append("published false_premise_failed does not recompute")
    observed_cost = round(
        sum(float(case.get("cost_cny", 0) or 0) for case in valid_cases), 8
    )
    ledger_sources = proof.get("ledger_sources")
    if not isinstance(ledger_sources, list) or len(ledger_sources) != 6:
        failures.append("proof must preserve six shard-ledger digests")
    elif any(
        not isinstance(item, dict)
        or re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256", ""))) is None
        for item in ledger_sources
    ):
        failures.append("every shard ledger must have a SHA-256 digest")
    if isinstance(metrics.get("total_cost_cny"), int | float) and metrics.get(
        "total_cost_cny"
    ) < observed_cost:
        failures.append("ledger total cost cannot be below recorded case costs")

    boundaries = proof.get("boundaries")
    if not isinstance(boundaries, dict):
        failures.append("baseline boundaries must be declared")
    else:
        if boundaries.get("capability_effect_claim") is not False:
            failures.append("F01 may not claim a capability effect")
        if boundaries.get("rerun_or_best_of") is not False:
            failures.append("F01 may not conceal a rerun or best-of selection")
        if boundaries.get("formal_product_metrics") is not False:
            failures.append("F01 diagnostics may not be labelled formal product metrics")
        if boundaries.get("f01_30_of_30_done") is not False:
            failures.append("F01 must preserve the incomplete 30/30 outcome")

    errors_by_id = {
        str(case.get("id")): case.get("error_type")
        for case in valid_cases
        if case.get("status") == "error"
    }
    required_failures = {
        "Q13": "LLMRetryExhaustedError",
        "Q21": "FileNotFoundError",
    }
    for qid, error_type in required_failures.items():
        if errors_by_id.get(qid) != error_type:
            failures.append(f"{qid}: required diagnostic failure {error_type} is missing")
    return failures


def _self_test(proof: dict[str, Any]) -> None:
    if evaluate(proof):
        raise SystemExit("f01_live_baseline_self_test=FAIL published proof is dirty")
    metrics = proof["metrics"]
    cases = proof["cases"]
    mutations = {
        "missing_question": {**proof, "cases": cases[:-1]},
        "fixture_retrieval": {
            **proof,
            "cases": [
                {
                    **cases[0],
                    "provider_fidelity": {
                        **cases[0]["provider_fidelity"],
                        "retrieval": "replay",
                    },
                },
                *cases[1:],
            ],
        },
        "missing_funnel_stage": {
            **proof,
            "cases": [
                {
                    **cases[0],
                    "evidence_funnel": {
                        key: value
                        for key, value in cases[0]["evidence_funnel"].items()
                        if key != "reader_visible_evidence"
                    },
                },
                *cases[1:],
            ],
        },
        "hidden_error": {
            **proof,
            "metrics": {**metrics, "completed_questions": 29, "error_questions": 1},
        },
        "cost_overrun": {
            **proof,
            "metrics": {**metrics, "total_cost_cny": 30.01},
        },
        "effect_overclaim": {
            **proof,
            "boundaries": {**proof["boundaries"], "capability_effect_claim": True},
        },
    }
    for label, broken in mutations.items():
        if not evaluate(broken):
            raise SystemExit(f"f01_live_baseline_self_test=FAIL accepted {label}")
    print(f"f01_live_baseline_self_test=PASS cases={len(mutations) + 1}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--proof", type=Path, default=PROOF)
    parser.add_argument("--build-from", type=Path)
    parser.add_argument("--ledger", action="append", type=Path, default=[])
    args = parser.parse_args()
    if args.build_from is not None:
        proof = build_proof(args.build_from, ledger_paths=args.ledger)
        args.proof.parent.mkdir(parents=True, exist_ok=True)
        args.proof.write_text(
            json.dumps(proof, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"written={args.proof}")
        return 0
    proof = json.loads(args.proof.read_text(encoding="utf-8"))
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
