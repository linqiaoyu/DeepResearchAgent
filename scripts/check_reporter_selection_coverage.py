"""Build and validate the F03 offline Reporter selection-consumption proof."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

from deepresearch_agent.agents import ReporterAgent
from deepresearch_agent.agents.reporter import prune_reference_list
from deepresearch_agent.citations import build_footnote_maps
from deepresearch_agent.reporting.reader_reach import (
    evidence_the_reader_can_follow,
    orphaned_sub_questions,
    reader_body,
)
from deepresearch_agent.schemas import ResearchState


ROOT = Path(__file__).resolve().parents[1]
PROOF = ROOT / "docs/decisions/151/reporter-selection-coverage-proof.json"
FOOTNOTE_REF = re.compile(r"\[\^(\d+)\]")
FOOTNOTE_DEF = re.compile(r"^\[\^(\d+)\]:", re.MULTILINE)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _restore_reference_catalog(
    report: str,
    reporter: ReporterAgent,
    state: ResearchState,
    footnotes: Any,
) -> str:
    body, marker, _references = report.partition("## 参考来源")
    show_source_tiers = any(
        item.source_tier != "unknown" or item.content_truncated
        for item in state.evidence_store
    )
    lines = reporter._reference_lines(
        footnotes,
        footnotes.evidence_id_to_footnote,
        show_source_tiers=show_source_tiers,
    )
    separator = "\n\n## 参考来源\n"
    return body.rstrip() + separator + "\n".join(lines) if marker else report


def _case(state_path: Path, report_path: Path, output_root: Path) -> dict[str, Any]:
    state = ResearchState.model_validate_json(state_path.read_text(encoding="utf-8"))
    original = report_path.read_text(encoding="utf-8")
    reporter = ReporterAgent()
    state.report_evidence_selections = reporter._select_report_evidence(
        state,
        context_evidence=None,
    )
    footnotes = build_footnote_maps(state.evidence_store)
    state.report_footnote_evidence = {
        number: item.id for number, item in footnotes.footnote_to_evidence.items()
    }
    restored = _restore_reference_catalog(original, reporter, state, footnotes)
    fixed = prune_reference_list(
        reporter._enforce_selected_evidence_coverage(
            restored,
            state,
            footnotes.evidence_id_to_footnote,
        )
    )
    output_root.mkdir(parents=True, exist_ok=True)
    output_path = output_root / f"{state_path.parent.name}-report.md"
    output_path.write_text(fixed + "\n", encoding="utf-8")
    reachable = evidence_the_reader_can_follow(state, fixed)
    selected_ids = {
        evidence_id
        for selection in state.report_evidence_selections
        for evidence_id in selection.evidence_ids
    }
    cited = {int(item) for item in FOOTNOTE_REF.findall(reader_body(fixed))}
    defined = {int(item) for item in FOOTNOTE_DEF.findall(fixed)}
    return {
        "id": state_path.parent.name,
        "state_artifact": str(state_path.relative_to(ROOT)),
        "state_sha256": _sha256(state_path),
        "report_artifact": str(report_path.relative_to(ROOT)),
        "report_sha256": _sha256(report_path),
        "output_artifact": str(output_path.relative_to(ROOT)),
        "output_sha256": _sha256(output_path),
        "original_orphaned_sub_questions": len(
            orphaned_sub_questions(state, original)
        ),
        "orphaned_sub_questions": len(orphaned_sub_questions(state, fixed)),
        "selected_evidence": len(selected_ids),
        "selected_evidence_covered": len(selected_ids & reachable),
        "footnote_misrefs": len(cited - defined),
    }


def build_proof(artifacts_root: Path) -> dict[str, Any]:
    artifacts_root = artifacts_root.resolve()
    pairs: list[tuple[Path, Path]] = []
    for state_path in sorted(artifacts_root.glob("shard*/work/Q*/state.json")):
        report_path = state_path.with_name("report.md")
        if report_path.is_file():
            pairs.append((state_path, report_path))
    records = [
        _case(state_path, report_path, ROOT / "artifacts/151/offline")
        for state_path, report_path in pairs
    ]
    selected = sum(item["selected_evidence"] for item in records)
    covered = sum(item["selected_evidence_covered"] for item in records)
    return {
        "round": 151,
        "status": "passed",
        "source_round": 149,
        "quality_claim": False,
        "records": records,
        "metrics": {
            "successful_recorded_cases": len(records),
            "original_orphaned_sub_questions": sum(
                item["original_orphaned_sub_questions"] for item in records
            ),
            "orphaned_sub_questions": sum(
                item["orphaned_sub_questions"] for item in records
            ),
            "selected_evidence": selected,
            "selected_evidence_covered": covered,
            "selected_evidence_coverage_rate": round(covered / selected, 6)
            if selected
            else 1.0,
            "footnote_misrefs": sum(item["footnote_misrefs"] for item in records),
        },
    }


def evaluate(proof: Any) -> list[str]:
    if not isinstance(proof, dict):
        return ["proof must be an object"]
    failures: list[str] = []
    if proof.get("round") != 151 or proof.get("status") != "passed":
        failures.append("proof must be the passed R151 result")
    if proof.get("source_round") != 149 or proof.get("quality_claim") is not False:
        failures.append("proof must be an offline R149 regression, not a quality claim")
    metrics = proof.get("metrics")
    if not isinstance(metrics, dict):
        return [*failures, "metrics must be an object"]
    exact = {
        "successful_recorded_cases": 28,
        "orphaned_sub_questions": 0,
        "footnote_misrefs": 0,
    }
    for name, expected in exact.items():
        if metrics.get(name) != expected:
            failures.append(f"{name} must equal {expected}, got {metrics.get(name)!r}")
    if metrics.get("selected_evidence_coverage_rate") != 1.0:
        failures.append("selected Evidence coverage rate must equal 1.0")
    if not isinstance(metrics.get("original_orphaned_sub_questions"), int) or metrics["original_orphaned_sub_questions"] < 1:
        failures.append("proof must include at least one real original orphan")
    records = proof.get("records")
    if not isinstance(records, list) or len(records) != 28:
        failures.append("proof must retain exactly 28 successful recorded cases")
    else:
        if len({item.get("id") for item in records if isinstance(item, dict)}) != 28:
            failures.append("recorded case ids must be unique")
        for record in records:
            if not isinstance(record, dict):
                failures.append("every record must be an object")
                continue
            for name in ("state_sha256", "report_sha256", "output_sha256"):
                value = record.get(name)
                if not isinstance(value, str) or len(value) != 64:
                    failures.append(f"{record.get('id')} has no {name}")
    return failures


def _self_test(proof: dict[str, Any]) -> None:
    if evaluate(proof):
        raise SystemExit("reporter_selection_coverage_self_test=FAIL proof is dirty")
    metrics = proof["metrics"]
    cases = {
        "orphan": {**proof, "metrics": {**metrics, "orphaned_sub_questions": 1}},
        "selected_drop": {
            **proof,
            "metrics": {**metrics, "selected_evidence_coverage_rate": 0.99},
        },
        "misref": {**proof, "metrics": {**metrics, "footnote_misrefs": 1}},
        "silent_exclusion": {
            **proof,
            "metrics": {**metrics, "successful_recorded_cases": 27},
        },
        "no_real_regression": {
            **proof,
            "metrics": {**metrics, "original_orphaned_sub_questions": 0},
        },
    }
    for label, broken in cases.items():
        if not evaluate(broken):
            raise SystemExit(
                f"reporter_selection_coverage_self_test=FAIL accepted {label}"
            )
    print(f"reporter_selection_coverage_self_test=PASS cases={len(cases) + 1}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--build-root", type=Path)
    args = parser.parse_args()
    if args.build_root is not None:
        proof = build_proof(args.build_root)
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
