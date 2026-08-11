"""Validate the published F11 live reliability canary without treating it as product proof."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PROOF = ROOT / "docs/decisions/158/live-canary-proof.json"
PREREGISTRATION = "docs/decisions/158/preregistration.json"
SOURCE_ARTIFACT = "artifacts/158/canary.json"
EXPECTED_IDS = ["Q01", "Q06", "Q09", "Q13", "Q16", "Q21", "Q28", "Q30"]
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
SHA256 = re.compile(r"[0-9a-f]{64}")


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _artifact_name(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT))


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: expected an object")
    return payload


def _ledger_rows(paths: list[Path]) -> tuple[list[dict[str, Any]], float]:
    rows: list[dict[str, Any]] = []
    total = 0.0
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
                total += float(row.get("cost_cny", 0) or 0)
    return rows, total


def build_proof(
    source_path: Path,
    *,
    ledger_paths: list[Path],
    runs_root: Path,
    shard_root: Path,
) -> dict[str, Any]:
    """Reduce ignored live artifacts to a content-free, reviewable proof."""

    source = _load(source_path)
    raw_results = source.get("results")
    if not isinstance(raw_results, list):
        raise ValueError("canary results must be a list")
    ledger_rows, ledger_cost = _ledger_rows(ledger_paths)
    cases: list[dict[str, Any]] = []
    for raw in raw_results:
        if not isinstance(raw, dict):
            raise ValueError("every canary result must be an object")
        qid = str(raw.get("id"))
        run_id = str(raw.get("research_id"))
        shard = "a" if qid in {"Q01", "Q06", "Q13", "Q16"} else "b"
        state_path = shard_root / f"shard-{shard}" / qid / "state.json"
        trajectory_path = runs_root / run_id / "trajectory.json"
        manifest_path = runs_root / run_id / "manifest.json"
        state = _load(state_path)
        trajectory = _load(trajectory_path)
        mechanical = raw.get("mechanical")
        if not isinstance(mechanical, dict):
            mechanical = {}
        funnel = mechanical.get("evidence_funnel")
        if not isinstance(funnel, dict):
            funnel = {}
        normalized_funnel = {
            name: int(funnel.get(name, 0) or 0) for name in sorted(FUNNEL_FIELDS)
        }
        planner_latencies = [
            float(row.get("latency_seconds", 0) or 0)
            for row in ledger_rows
            if row.get("run_id") == run_id and row.get("role") == "planner"
        ]
        termination = trajectory.get("termination")
        if not isinstance(termination, dict):
            termination = {}
        workflow_status = str(termination.get("status", state.get("status", "unknown")))
        cases.append(
            {
                "id": qid,
                "run_id": run_id,
                "shard_ledger_authority": shard,
                "outer_status": raw.get("status"),
                "workflow_status": workflow_status,
                "termination_error_type": termination.get("error_type"),
                "termination_error_message": termination.get("error_message"),
                "provider_fidelity": raw.get("provider_fidelity"),
                "planner_latency_seconds": (
                    round(planner_latencies[0], 6) if len(planner_latencies) == 1 else None
                ),
                "evidence_funnel": normalized_funnel,
                "locators": {
                    "state": {
                        "artifact": _artifact_name(state_path),
                        "sha256": _digest(state_path),
                    },
                    "trajectory": {
                        "artifact": _artifact_name(trajectory_path),
                        "sha256": _digest(trajectory_path),
                    },
                    "manifest": {
                        "artifact": _artifact_name(manifest_path),
                        "sha256": _digest(manifest_path),
                    },
                },
            }
        )
    cases.sort(key=lambda item: EXPECTED_IDS.index(item["id"]))
    planner_timeouts = sum(
        case["termination_error_type"] in {"LLMTimeoutError", "TimeoutError"}
        and "planner" in str(case.get("termination_error_message", "")).lower()
        for case in cases
    )
    budget_failures = [
        case["id"] for case in cases if case["workflow_status"] == "budget_exceeded"
    ]
    ledger_sources = [
        {
            "authority": "a" if path.name.startswith("ledger-a") else "b",
            "artifact": _artifact_name(path),
            "sha256": _digest(path),
        }
        for path in ledger_paths
    ]
    reliability_passed = not budget_failures and planner_timeouts == 0
    return {
        "schema_version": "f11-live-canary-v1",
        "round": 158,
        "task": "F11",
        "status": "reliability_passed" if reliability_passed else "reliability_failed",
        "preregistration": PREREGISTRATION,
        "source": {"artifact": SOURCE_ARTIFACT, "sha256": _digest(source_path)},
        "ledger_sources": ledger_sources,
        "metrics": {
            "question_count": len(cases),
            "terminal_artifacts": sum(
                case["outer_status"] in {"done", "error"} for case in cases
            ),
            "outer_done": sum(case["outer_status"] == "done" for case in cases),
            "workflow_completed": sum(
                case["workflow_status"] == "completed" for case in cases
            ),
            "workflow_budget_exceeded": len(budget_failures),
            "planner_timeouts": planner_timeouts,
            "ledger_collisions": 0,
            "silent_exclusions": len(set(EXPECTED_IDS) - {case["id"] for case in cases}),
            "live_fidelity_cases": sum(
                case["provider_fidelity"] == EXPECTED_FIDELITY for case in cases
            ),
            "locator_complete_cases": sum(
                set(case["locators"]) == {"state", "trajectory", "manifest"}
                for case in cases
            ),
            "round_ledger_cost_cny": round(ledger_cost, 8),
            "round_fuse_cny": 12.0,
        },
        "cases": cases,
        "failure_findings": [
            {
                "id": qid,
                "class": "critic_retry_external_request_budget_exhaustion",
                "route": "F12",
            }
            for qid in budget_failures
        ],
        "integrity_findings": [
            {
                "id": case["id"],
                "outer_status": case["outer_status"],
                "workflow_status": case["workflow_status"],
                "class": "runner_terminal_status_mismatch",
                "route": "F12",
            }
            for case in cases
            if case["outer_status"] == "done" and case["workflow_status"] != "completed"
        ],
        "boundaries": {
            "formal_product_metrics": False,
            "capability_effect_claim": False,
            "may_contribute_to_f14": False,
            "saved_states": False,
            "rerun_or_best_of": False,
            "failed_case_reruns": 0,
        },
    }


def evaluate(proof: Any) -> list[str]:
    if not isinstance(proof, dict):
        return ["proof must be an object"]
    failures: list[str] = []
    if proof.get("schema_version") != "f11-live-canary-v1":
        failures.append("schema_version must be f11-live-canary-v1")
    if proof.get("round") != 158 or proof.get("task") != "F11":
        failures.append("proof must describe R158 F11")
    if proof.get("status") != "reliability_failed":
        failures.append("R158 must preserve the observed reliability failure")
    if proof.get("preregistration") != PREREGISTRATION:
        failures.append("proof must point to the fixed R158 preregistration")
    source = proof.get("source")
    if not isinstance(source, dict) or source.get("artifact") != SOURCE_ARTIFACT:
        failures.append("proof must identify the exact-once merged canary artifact")
    elif SHA256.fullmatch(str(source.get("sha256", ""))) is None:
        failures.append("source must have a SHA-256 digest")

    metrics = proof.get("metrics")
    if not isinstance(metrics, dict):
        return [*failures, "metrics must be an object"]
    expected = {
        "question_count": 8,
        "terminal_artifacts": 8,
        "outer_done": 8,
        "workflow_completed": 7,
        "workflow_budget_exceeded": 1,
        "planner_timeouts": 0,
        "ledger_collisions": 0,
        "silent_exclusions": 0,
        "live_fidelity_cases": 8,
        "locator_complete_cases": 8,
        "round_fuse_cny": 12.0,
    }
    for name, value in expected.items():
        if metrics.get(name) != value:
            failures.append(f"{name}: expected {value!r}, got {metrics.get(name)!r}")
    cost = metrics.get("round_ledger_cost_cny")
    if not isinstance(cost, int | float) or cost < 0 or cost > 12:
        failures.append("round ledger cost must remain within the CNY 12 fuse")

    cases = proof.get("cases")
    if not isinstance(cases, list) or len(cases) != 8:
        return [*failures, "cases must contain exactly eight entries"]
    ids = [str(case.get("id")) for case in cases if isinstance(case, dict)]
    if ids != EXPECTED_IDS or len(set(ids)) != 8:
        failures.append("cases must be the fixed eight IDs in preregistered order exactly once")
    for case in cases:
        if not isinstance(case, dict):
            failures.append("every case must be an object")
            continue
        qid = case.get("id")
        if case.get("outer_status") != "done":
            failures.append(f"{qid}: outer result must preserve its observed done status")
        if case.get("provider_fidelity") != EXPECTED_FIDELITY:
            failures.append(f"{qid}: configured provider fidelity is not live/live/live")
        latency = case.get("planner_latency_seconds")
        if not isinstance(latency, int | float) or latency < 0 or latency >= 180:
            failures.append(f"{qid}: planner latency must be recorded below 180 seconds")
        funnel = case.get("evidence_funnel")
        if not isinstance(funnel, dict) or set(funnel) != FUNNEL_FIELDS:
            failures.append(f"{qid}: five-stage evidence funnel is incomplete")
        locators = case.get("locators")
        if not isinstance(locators, dict) or set(locators) != {
            "state",
            "trajectory",
            "manifest",
        }:
            failures.append(f"{qid}: state/trajectory/manifest locators are incomplete")
        else:
            for kind, locator in locators.items():
                if (
                    not isinstance(locator, dict)
                    or not str(locator.get("artifact", "")).strip()
                    or SHA256.fullmatch(str(locator.get("sha256", ""))) is None
                ):
                    failures.append(f"{qid}: {kind} locator is invalid")

    by_id = {case.get("id"): case for case in cases if isinstance(case, dict)}
    for qid in EXPECTED_IDS:
        expected_status = "budget_exceeded" if qid == "Q13" else "completed"
        if by_id.get(qid, {}).get("workflow_status") != expected_status:
            failures.append(f"{qid}: workflow status must preserve {expected_status}")
    q13 = by_id.get("Q13", {})
    if q13.get("termination_error_type") != "ToolExecutionError" or "20/20" not in str(
        q13.get("termination_error_message", "")
    ):
        failures.append("Q13 must preserve its run-wide search-budget termination")
    if len({case.get("shard_ledger_authority") for case in cases}) != 2:
        failures.append("cases must identify two distinct shard ledger authorities")

    ledger_sources = proof.get("ledger_sources")
    if not isinstance(ledger_sources, list) or len(ledger_sources) != 2:
        failures.append("proof must preserve two shard-ledger digests")
    elif {item.get("authority") for item in ledger_sources if isinstance(item, dict)} != {
        "a",
        "b",
    }:
        failures.append("ledger authorities must be distinct a and b")
    elif any(
        SHA256.fullmatch(str(item.get("sha256", ""))) is None
        for item in ledger_sources
        if isinstance(item, dict)
    ):
        failures.append("every shard ledger must have a SHA-256 digest")

    expected_failure = [
        {
            "id": "Q13",
            "class": "critic_retry_external_request_budget_exhaustion",
            "route": "F12",
        }
    ]
    if proof.get("failure_findings") != expected_failure:
        failures.append("Q13 budget failure must be routed to F12")
    integrity = proof.get("integrity_findings")
    if not isinstance(integrity, list) or len(integrity) != 1:
        failures.append("the Q13 outer/workflow status mismatch must be explicit")
    elif integrity[0].get("id") != "Q13" or integrity[0].get("route") != "F12":
        failures.append("Q13 terminal-status mismatch must be routed to F12")

    boundaries = proof.get("boundaries")
    expected_boundaries = {
        "formal_product_metrics": False,
        "capability_effect_claim": False,
        "may_contribute_to_f14": False,
        "saved_states": False,
        "rerun_or_best_of": False,
        "failed_case_reruns": 0,
    }
    if boundaries != expected_boundaries:
        failures.append("canary boundaries must forbid product/effect claims and reruns")
    return failures


def _self_test(proof: dict[str, Any]) -> None:
    if evaluate(proof):
        raise SystemExit("f11_live_canary_self_test=FAIL published proof is dirty")
    cases: dict[str, dict[str, Any]] = {}
    hidden_failure = copy.deepcopy(proof)
    hidden_failure["cases"][3]["workflow_status"] = "completed"
    cases["hidden_q13_failure"] = hidden_failure
    product_claim = copy.deepcopy(proof)
    product_claim["boundaries"]["formal_product_metrics"] = True
    cases["product_overclaim"] = product_claim
    missing_locator = copy.deepcopy(proof)
    del missing_locator["cases"][0]["locators"]["trajectory"]
    cases["missing_trajectory"] = missing_locator
    planner_timeout = copy.deepcopy(proof)
    planner_timeout["metrics"]["planner_timeouts"] = 1
    cases["planner_timeout"] = planner_timeout
    same_ledger = copy.deepcopy(proof)
    same_ledger["ledger_sources"][1]["authority"] = "a"
    cases["shared_ledger"] = same_ledger
    for label, broken in cases.items():
        if not evaluate(broken):
            raise SystemExit(f"f11_live_canary_self_test=FAIL accepted {label}")
    print(f"f11_live_canary_self_test=PASS cases={len(cases) + 1}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--proof", type=Path, default=PROOF)
    parser.add_argument("--build-from", type=Path)
    parser.add_argument("--ledger", action="append", type=Path, default=[])
    parser.add_argument("--runs-root", type=Path, default=ROOT / "runs")
    parser.add_argument("--shard-root", type=Path, default=ROOT / "artifacts/158")
    parser.add_argument(
        "--mutate",
        choices=("hide-q13-failure", "claim-product-metric"),
        help="Intentional negative control used to preserve a real failure output.",
    )
    args = parser.parse_args()
    if args.build_from is not None:
        if len(args.ledger) != 2:
            raise SystemExit("--build-from requires exactly two --ledger paths")
        proof = build_proof(
            args.build_from,
            ledger_paths=args.ledger,
            runs_root=args.runs_root,
            shard_root=args.shard_root,
        )
        args.proof.parent.mkdir(parents=True, exist_ok=True)
        args.proof.write_text(
            json.dumps(proof, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"written={args.proof}")
        return 0
    proof = _load(args.proof)
    if args.mutate == "hide-q13-failure":
        proof["cases"][3]["workflow_status"] = "completed"
    elif args.mutate == "claim-product-metric":
        proof["boundaries"]["formal_product_metrics"] = True
    if args.self_test:
        _self_test(proof)
    failures = evaluate(proof)
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print(
        "f11_live_canary=PASS "
        f"cases={proof['metrics']['question_count']} "
        f"workflow_completed={proof['metrics']['workflow_completed']} "
        f"workflow_budget_exceeded={proof['metrics']['workflow_budget_exceeded']} "
        f"formal_product_metrics={str(proof['boundaries']['formal_product_metrics']).lower()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
