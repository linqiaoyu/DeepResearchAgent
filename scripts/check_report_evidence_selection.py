"""Validate the F02 pre-writing Evidence selection contract."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

from deepresearch_agent.agents import ReporterAgent
from deepresearch_agent.reporting.reader_reach import orphaned_sub_questions
from deepresearch_agent.schemas import ResearchState


ROOT = Path(__file__).resolve().parents[1]
PROOF = ROOT / "docs/decisions/150/evidence-selection-proof.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _snapshot(state: ResearchState) -> dict[str, Any]:
    assert state.plan is not None
    return {
        "plan_sub_question_ids": [item.id for item in state.plan.sub_questions],
        "evidence": [
            {"id": item.id, "sub_question_id": item.sub_question_id}
            for item in state.evidence_store
        ],
        "selections": [
            item.model_dump(mode="json") for item in state.report_evidence_selections
        ],
    }


def evaluate_snapshot(snapshot: Any) -> list[str]:
    if not isinstance(snapshot, dict):
        return ["selection snapshot must be an object"]
    plan_ids = snapshot.get("plan_sub_question_ids")
    evidence = snapshot.get("evidence")
    selections = snapshot.get("selections")
    if not isinstance(plan_ids, list) or not all(isinstance(item, str) for item in plan_ids):
        return ["plan sub-question ids must be strings"]
    if not isinstance(evidence, list) or not isinstance(selections, list):
        return ["evidence and selections must be lists"]
    failures: list[str] = []
    evidence_owner: dict[str, str] = {}
    evidence_by_sub_question: dict[str, set[str]] = {}
    for row in evidence:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not isinstance(row.get("sub_question_id"), str):
            failures.append("every Evidence row must carry id and sub_question_id")
            continue
        evidence_id = row["id"]
        owner = row["sub_question_id"]
        evidence_owner[evidence_id] = owner
        evidence_by_sub_question.setdefault(owner, set()).add(evidence_id)
    by_sub_question: dict[str, list[dict[str, Any]]] = {}
    for selection in selections:
        if not isinstance(selection, dict) or not isinstance(selection.get("sub_question_id"), str):
            failures.append("every selection must identify a sub-question")
            continue
        by_sub_question.setdefault(selection["sub_question_id"], []).append(selection)
    for sub_question_id in plan_ids:
        decisions = by_sub_question.get(sub_question_id, [])
        if len(decisions) != 1:
            failures.append(
                f"{sub_question_id} must have exactly one selection decision"
            )
            continue
        decision = decisions[0]
        owned = evidence_by_sub_question.get(sub_question_id, set())
        selected_ids = decision.get("evidence_ids")
        if not isinstance(selected_ids, list) or not all(
            isinstance(item, str) for item in selected_ids
        ):
            failures.append(f"{sub_question_id} evidence_ids must be strings")
            continue
        if owned:
            if decision.get("status") != "selected" or not selected_ids:
                failures.append(f"{sub_question_id} has Evidence but no selection")
            for evidence_id in selected_ids:
                if evidence_owner.get(evidence_id) != sub_question_id:
                    failures.append(
                        f"{sub_question_id} selected illegal Evidence {evidence_id}"
                    )
        elif (
            decision.get("status") != "degraded"
            or selected_ids
            or not decision.get("reason")
        ):
            failures.append(
                f"{sub_question_id} has no Evidence and must explicitly degrade"
            )
    extra = set(by_sub_question) - set(plan_ids)
    if extra:
        failures.append(f"selection contains unknown sub-questions: {sorted(extra)}")
    return failures


def evaluate(proof: Any) -> list[str]:
    if not isinstance(proof, dict):
        return ["proof must be an object"]
    failures: list[str] = []
    if proof.get("round") != 150 or proof.get("status") != "passed":
        failures.append("proof must be the passed R150 result")
    source = proof.get("source")
    if not isinstance(source, dict):
        failures.append("proof source is missing")
    else:
        for name in ("state_sha256", "report_sha256"):
            value = source.get(name)
            if not isinstance(value, str) or len(value) != 64:
                failures.append(f"source {name} must be a SHA-256 digest")
    accepted = proof.get("accepted_real_state")
    failures.extend(evaluate_snapshot(accepted))
    counterexample = proof.get("real_report_counterexample")
    if not isinstance(counterexample, dict):
        failures.append("real report counterexample is missing")
    else:
        counter_failures = evaluate_snapshot(counterexample.get("snapshot"))
        if not counter_failures:
            failures.append("real report counterexample must fail selection validation")
        recorded = counterexample.get("guard_failures")
        if recorded != counter_failures:
            failures.append("counterexample failures must be recomputed exactly")
        orphan_ids = counterexample.get("orphaned_sub_question_ids")
        if not isinstance(orphan_ids, list) or not orphan_ids:
            failures.append("counterexample must identify a real orphaned sub-question")
    return failures


def build_proof(state_path: Path, report_path: Path) -> dict[str, Any]:
    state_path = state_path.resolve()
    report_path = report_path.resolve()
    state = ResearchState.model_validate_json(state_path.read_text(encoding="utf-8"))
    report = report_path.read_text(encoding="utf-8")
    raw_snapshot = _snapshot(state)
    real_orphans = [item[0] for item in orphaned_sub_questions(state, report)]
    state.report_evidence_selections = ReporterAgent()._select_report_evidence(
        state,
        context_evidence=None,
    )
    return {
        "round": 150,
        "status": "passed",
        "source": {
            "state_artifact": str(state_path.relative_to(ROOT)),
            "state_sha256": _sha256(state_path),
            "report_artifact": str(report_path.relative_to(ROOT)),
            "report_sha256": _sha256(report_path),
        },
        "accepted_real_state": _snapshot(state),
        "real_report_counterexample": {
            "snapshot": raw_snapshot,
            "orphaned_sub_question_ids": real_orphans,
            "guard_failures": evaluate_snapshot(raw_snapshot),
        },
        "metrics": {
            "planned_sub_questions": len(state.plan.sub_questions if state.plan else []),
            "selection_decisions": len(state.report_evidence_selections),
            "illegal_evidence_ids": 0,
            "real_counterexamples_rejected": 1,
        },
    }


def _self_test(proof: dict[str, Any]) -> None:
    if evaluate(proof):
        raise SystemExit("report_evidence_selection_self_test=FAIL proof is dirty")
    accepted = proof["accepted_real_state"]
    selections = accepted["selections"]
    cases = {
        "missing_decision": {
            **proof,
            "accepted_real_state": {**accepted, "selections": selections[1:]},
        },
        "illegal_id": {
            **proof,
            "accepted_real_state": {
                **accepted,
                "selections": [
                    {**selections[0], "evidence_ids": ["invented-evidence"]},
                    *selections[1:],
                ],
            },
        },
        "counterexample_passes": {
            **proof,
            "real_report_counterexample": {
                **proof["real_report_counterexample"],
                "snapshot": accepted,
                "guard_failures": [],
            },
        },
    }
    for label, broken in cases.items():
        if not evaluate(broken):
            raise SystemExit(
                f"report_evidence_selection_self_test=FAIL accepted {label}"
            )
    print(f"report_evidence_selection_self_test=PASS cases={len(cases) + 1}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--build-state", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.build_state is not None:
        if args.report is None:
            parser.error("--build-state requires --report")
        proof = build_proof(args.build_state, args.report)
        PROOF.parent.mkdir(parents=True, exist_ok=True)
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
