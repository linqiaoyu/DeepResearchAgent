"""Validate the F08 finance-capability pre-screen and its zero-cost boundary."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PRESCREEN_PATH = ROOT / "data/capability_prescreen.json"
GRADUATION_PATH = ROOT / "data/capability_graduation.json"
CORPUS_PATH = ROOT / "data/corpus/finance_v3.json"
QUESTIONS_PATH = ROOT / "data/golden_set/v1/questions.json"
EXPECTED_METRICS = {
    "evidence_reachable_rate",
    "orphaned_sub_questions",
    "false_premise_failed",
}
EXPECTED_CAPABILITIES = {
    "INJECTION_GUARD_ENABLED",
    "LLM_TOOL_SELECTION_ENABLED",
    "MCP_CLIENT_ENABLED",
    "PRIOR_MEMORY_ENABLED",
    "PROCEDURAL_MEMORY_ENABLED",
    "RAG_ENABLED",
    "REFLECTION_ENABLED",
    "RESEARCH_LOOP_ENABLED",
    "SKILL_PACKS_ENABLED",
}
VALID_DECISIONS = {"permanent_opt_in", "paired_experiment"}


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _observed_rag_scope() -> dict[str, int]:
    corpus = _load(CORPUS_PATH)
    questions = _load(QUESTIONS_PATH)
    paths = [str(item.get("path", "")) for item in corpus.get("documents", [])]
    issuers = {path.split("_", maxsplit=1)[0] for path in paths if path}
    companies = {
        str(company)
        for question in questions.get("questions", [])
        for company in question.get("companies", [])
        if str(company)
    }
    return {
        "corpus_documents": len(paths),
        "corpus_issuers": len(issuers),
        "cohort_named_companies": len(companies),
        "direct_company_overlap": len(issuers & companies),
    }


def evaluate(
    payload: Any,
    graduation: Any,
    *,
    rag_scope: dict[str, int] | None = None,
) -> list[str]:
    if not isinstance(payload, dict) or not isinstance(graduation, dict):
        return ["prescreen and graduation registries must be objects"]
    failures: list[str] = []
    if payload.get("schema_version") != "f08-capability-prescreen-v1":
        failures.append("schema_version must be f08-capability-prescreen-v1")
    if payload.get("round") != 156:
        failures.append("round must be 156")
    if set(payload.get("product_metrics", [])) != EXPECTED_METRICS:
        failures.append("product_metrics must be the three frozen acceptance metrics")
    capabilities = payload.get("capabilities")
    if not isinstance(capabilities, dict):
        return failures + ["capabilities must be an object"]
    if set(capabilities) != EXPECTED_CAPABILITIES:
        failures.append(
            "all and only the nine default-off capabilities must receive a decision"
        )

    graduation_entries = graduation.get("capabilities", {})
    candidates: set[str] = set()
    for name, entry in capabilities.items():
        if not isinstance(entry, dict):
            failures.append(f"{name}: decision must be an object")
            continue
        decision = entry.get("decision")
        if decision not in VALID_DECISIONS:
            failures.append(f"{name}: invalid decision {decision!r}")
            continue
        if not str(entry.get("reason", "")).strip():
            failures.append(f"{name}: decision reason must be non-empty")
        registered = graduation_entries.get(name, {})
        if decision == "permanent_opt_in":
            if entry.get("metric_path") != "none":
                failures.append(f"{name}: opt-in without an experiment must use metric_path=none")
            if registered.get("status") != "opt_in":
                failures.append(f"{name}: permanent opt-in must match graduation status=opt_in")
        else:
            candidates.add(name)
            design = entry.get("experiment_design")
            if not isinstance(design, dict):
                failures.append(f"{name}: paired experiment requires experiment_design")
                continue
            if design.get("primary_metric") not in EXPECTED_METRICS:
                failures.append(f"{name}: experiment primary_metric is not frozen")
            required = {
                "hypothesis",
                "noise_estimate",
                "sample_size_derivation",
                "minimum_pairs",
                "cost_ceiling_cny",
                "decision_rule",
            }
            missing = required - set(design)
            if missing:
                failures.append(f"{name}: experiment design missing {sorted(missing)}")
            if int(design.get("minimum_pairs", 0)) < 2:
                failures.append(f"{name}: minimum_pairs must be at least 2")
            if float(design.get("cost_ceiling_cny", 0)) <= 0:
                failures.append(f"{name}: cost ceiling must be positive")

    declared_candidates = set(payload.get("paid_experiment_candidates", []))
    if declared_candidates != candidates:
        failures.append("paid_experiment_candidates must equal paired_experiment decisions")
    if payload.get("paid_experiments_planned") != len(candidates):
        failures.append("paid_experiments_planned must equal the candidate count")
    if payload.get("full_cohort_runs_authorized") != 0:
        failures.append("F08 may authorize zero full-cohort runs")
    if payload.get("cost_cny") != 0:
        failures.append("F08 pre-screen cost must be CNY 0")

    rag_entry = capabilities.get("RAG_ENABLED", {})
    observed = rag_scope or _observed_rag_scope()
    for key, value in observed.items():
        if rag_entry.get(key) != value:
            failures.append(f"RAG_ENABLED: {key} must equal observed {value}")
    return failures


def _self_test(payload: dict[str, Any], graduation: dict[str, Any]) -> None:
    if evaluate(payload, graduation):
        raise SystemExit("capability_prescreen_self_test=FAIL current registries are dirty")
    cases: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}

    missing = copy.deepcopy(payload)
    del missing["capabilities"]["RAG_ENABLED"]
    cases["missing_decision"] = (missing, graduation)

    false_scope = copy.deepcopy(payload)
    false_scope["capabilities"]["RAG_ENABLED"]["direct_company_overlap"] = 1
    cases["false_rag_scope"] = (false_scope, graduation)

    unpowered = copy.deepcopy(payload)
    unpowered["capabilities"]["RAG_ENABLED"].update(
        {"decision": "paired_experiment", "metric_path": "evidence_reachable_rate"}
    )
    unpowered["paid_experiment_candidates"] = ["RAG_ENABLED"]
    unpowered["paid_experiments_planned"] = 1
    cases["unpowered_experiment"] = (unpowered, graduation)

    pending = copy.deepcopy(graduation)
    pending["capabilities"]["REFLECTION_ENABLED"]["status"] = "pending"
    cases["registry_mismatch"] = (payload, pending)

    for label, (broken, registry) in cases.items():
        if not evaluate(broken, registry):
            raise SystemExit(f"capability_prescreen_self_test=FAIL accepted {label}")
    print(f"capability_prescreen_self_test=PASS cases={len(cases) + 1}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument(
        "--mutate",
        choices=("rag-overlap", "pending-reflection"),
        help="Intentional negative control used to preserve a real failure output.",
    )
    args = parser.parse_args()
    payload = _load(PRESCREEN_PATH)
    graduation = _load(GRADUATION_PATH)
    if args.mutate == "rag-overlap":
        payload["capabilities"]["RAG_ENABLED"]["direct_company_overlap"] = 1
    elif args.mutate == "pending-reflection":
        graduation["capabilities"]["REFLECTION_ENABLED"]["status"] = "pending"
    if args.self_test:
        _self_test(payload, graduation)
    failures = evaluate(payload, graduation)
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print(
        "capability_prescreen=PASS "
        f"decisions={len(payload['capabilities'])} "
        f"paid_candidates={len(payload['paid_experiment_candidates'])} "
        f"pending={sum(1 for item in graduation['capabilities'].values() if item.get('status') == 'pending')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
