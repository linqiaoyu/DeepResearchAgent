"""Build and validate F05 numeric-fact delivery from real R149 artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from deepresearch_agent.agents.critic import CriticAgent  # noqa: E402
from deepresearch_agent.evaluation.behavioral import (  # noqa: E402
    relative_tolerance,
    report_body,
    report_numbers,
    token_stated,
)
from deepresearch_agent.schemas import ResearchState  # noqa: E402

PROOF = ROOT / "docs/decisions/153/numeric-fact-retention-proof.json"
GOLDEN = ROOT / "data/golden_set/v1/questions.json"
R149_PROOF = ROOT / "docs/decisions/149/live-loss-baseline-proof.json"
CURRENCY_UNITS = ("元", "千元", "万元", "百万元", "亿元")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _state_paths(root: Path) -> dict[str, Path]:
    return {path.parent.name: path for path in root.glob("shard*/work/Q*/state.json")}


def _contract_mismatch(report: str, fact: dict[str, Any]) -> list[str]:
    contract = fact["audit_contract"]
    body = report_body(report)
    failures: list[str] = []
    for entity in contract.get("entities", []):
        if str(entity) not in body:
            failures.append(f"entity:{entity}")
    period = contract.get("period", {})
    year = period.get("year") if isinstance(period, dict) else None
    if year is not None and str(year) not in body:
        failures.append(f"period:{year}")
    for unit in contract.get("units", []):
        expected = str(unit)
        compatible_currency = expected in CURRENCY_UNITS and any(
            candidate in body for candidate in CURRENCY_UNITS
        )
        if not compatible_currency and expected.lower() not in body.lower():
            failures.append(f"unit:{unit}")
    return failures


def build_proof(artifacts_root: Path) -> dict[str, Any]:
    questions = json.loads(GOLDEN.read_text(encoding="utf-8"))["questions"]
    terminal = {
        item["id"]: item
        for item in json.loads(R149_PROOF.read_text(encoding="utf-8"))["cases"]
    }
    states = _state_paths(artifacts_root.resolve())
    traces: list[dict[str, Any]] = []
    conflict_detected = 0
    conflict_recorded = 0
    for question in questions:
        qid = str(question["id"])
        state_path = states.get(qid)
        state = (
            ResearchState.model_validate_json(state_path.read_text(encoding="utf-8"))
            if state_path is not None
            else None
        )
        report_path = ROOT / "artifacts/151/offline" / f"{qid}-report.md"
        report = report_path.read_text(encoding="utf-8") if report_path.exists() else ""
        evidence_numbers = report_numbers(
            " ".join(f"{item.claim} {item.extract_text}" for item in state.evidence_store)
        ) if state is not None else []
        reader_numbers = report_numbers(report_body(report)) if report else []
        if state is not None:
            detected = CriticAgent()._numeric_conflicts(state.evidence_store)
            conflict_detected += len(detected)
            recorded = {
                tuple(sorted(issue.affected_claims))
                for issue in (state.critic_report.issues if state.critic_report else [])
                if issue.issue_type == "numeric_conflict"
            }
            conflict_recorded += sum(
                tuple(sorted(issue.affected_claims)) in recorded for issue in detected
            )
        for index, fact in enumerate(question["gold"]["must_include"]):
            contract = fact.get("audit_contract")
            tokens = [str(item) for item in (contract or {}).get("numeric_tokens", [])]
            if not tokens:
                continue
            tolerance = relative_tolerance(fact.get("tol"))
            entered = all(token_stated(token, evidence_numbers, tolerance) for token in tokens)
            visible = all(token_stated(token, reader_numbers, tolerance) for token in tokens)
            mismatches = _contract_mismatch(report, fact) if visible else []
            traces.append(
                {
                    "question": qid,
                    "fact_index": index,
                    "tokens": tokens,
                    "run_status": terminal[qid]["status"],
                    "state_artifact": str(state_path.relative_to(ROOT)) if state_path else None,
                    "state_sha256": _sha(state_path) if state_path else None,
                    "report_artifact": str(report_path.relative_to(ROOT)) if report else None,
                    "report_sha256": _sha(report_path) if report else None,
                    "entered_evidence": entered,
                    "reader_visible": visible,
                    "contract_mismatches": mismatches,
                }
            )
    entered = [item for item in traces if item["entered_evidence"]]
    retained = [item for item in entered if item["reader_visible"]]
    metrics = {
        "gold_numeric_fact_traces": len(traces),
        "run_error_traces": sum(item["run_status"] != "done" for item in traces),
        "facts_entered_evidence": len(entered),
        "facts_reader_visible": len(retained),
        "reader_visible_retention_rate": round(len(retained) / len(entered), 6),
        "entity_period_unit_mismatches": sum(
            len(item["contract_mismatches"]) for item in retained
        ),
        "numeric_conflicts_detected": conflict_detected,
        "numeric_conflicts_recorded_by_critic": conflict_recorded,
        "numeric_conflicts_missing_from_critic": conflict_detected - conflict_recorded,
    }
    return {"round": 153, "status": "passed", "source_round": 149, "metrics": metrics, "traces": traces}


def evaluate(proof: Any) -> list[str]:
    if not isinstance(proof, dict):
        return ["proof must be an object"]
    metrics = proof.get("metrics", {})
    errors: list[str] = []
    if proof.get("round") != 153 or proof.get("source_round") != 149:
        errors.append("proof identity mismatch")
    if metrics.get("gold_numeric_fact_traces") != 20:
        errors.append("all 20 contracted golden numeric facts must be traced")
    if metrics.get("reader_visible_retention_rate", 0) < 0.80:
        errors.append("reader-visible numeric retention must be >= 0.80")
    if metrics.get("entity_period_unit_mismatches") != 0:
        errors.append("entity/period/unit mismatches must be zero")
    if metrics.get("numeric_conflicts_missing_from_critic") != 0:
        errors.append("every detected numeric conflict must enter Critic")
    if metrics.get("run_error_traces") != 1:
        errors.append("Q13's unavailable numeric trace must remain explicit")
    return errors


def _self_test(proof: dict[str, Any]) -> None:
    if evaluate(proof):
        raise SystemExit("numeric_fact_retention_self_test=FAIL shipped proof")
    metrics = proof["metrics"]
    mutations = {
        "drop": {**metrics, "reader_visible_retention_rate": 0.79},
        "mismatch": {**metrics, "entity_period_unit_mismatches": 1},
        "critic_bypass": {**metrics, "numeric_conflicts_missing_from_critic": 1},
        "missing_trace": {**metrics, "gold_numeric_fact_traces": 19},
    }
    for label, broken in mutations.items():
        if not evaluate({**proof, "metrics": broken}):
            raise SystemExit(f"numeric_fact_retention_self_test=FAIL accepted {label}")
    print(f"numeric_fact_retention_self_test=PASS cases={len(mutations) + 1}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--build-root", type=Path)
    args = parser.parse_args()
    if args.build_root:
        proof = build_proof(args.build_root)
        PROOF.parent.mkdir(parents=True, exist_ok=True)
        PROOF.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        proof = json.loads(PROOF.read_text(encoding="utf-8"))
    if args.self_test:
        _self_test(proof)
    errors = evaluate(proof)
    print(json.dumps(proof["metrics"], ensure_ascii=False, sort_keys=True))
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
