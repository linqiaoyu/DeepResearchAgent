"""Prove the Reporter rejects a premise contradicted by selected evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from deepresearch_agent.agents import ReporterAgent  # noqa: E402
from deepresearch_agent.citations import build_footnote_maps  # noqa: E402
from deepresearch_agent.domains.registry import load_domain_pack  # noqa: E402
from deepresearch_agent.evaluation.behavioral import refute_premise_verdict  # noqa: E402
from deepresearch_agent.schemas import (  # noqa: E402
    Evidence,
    ReportEvidenceSelection,
    ResearchState,
)


FIXTURE = ROOT / "tests/fixtures/behavioral/r160_live_q16_premise_input.json"
QUESTIONS = ROOT / "data/golden_set/v1/questions.json"


def _load_case() -> tuple[ResearchState, str, dict[str, Any]]:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    state = ResearchState(topic=raw["topic"])
    state.evidence_store = [
        Evidence(
            research_id=state.research_id,
            claim_type="fact",
            extract_text=item["claim"],
            **item,
        )
        for item in raw["evidence"]
    ]
    state.report_evidence_selections = [
        ReportEvidenceSelection(
            sub_question_id="premise",
            status="selected",
            evidence_ids=[item.id for item in state.evidence_store],
            delivery_mode="reporter_context",
            reason="reduced_real_r160_selection",
        )
    ]
    questions = json.loads(QUESTIONS.read_text(encoding="utf-8"))["questions"]
    gold = next(item["gold"] for item in questions if item["id"] == "Q16")
    return state, raw["failing_report_excerpt"], gold


def evaluate(*, bypass_filter: bool = False, overclaim_unresolved: bool = False) -> list[str]:
    failures: list[str] = []
    state, failing_report, gold = _load_case()
    domain_pack = load_domain_pack("finance")
    assessment = domain_pack.assess_premise(
        state.topic, state.evidence_store, state.report_evidence_selections
    )
    if assessment.status != "contradicted":
        failures.append("real R160 selected evidence must contradict the topic premise")
    selected = {
        evidence_id
        for selection in state.report_evidence_selections
        for evidence_id in selection.evidence_ids
    }
    if not assessment.evidence_ids or not set(assessment.evidence_ids) <= selected:
        failures.append("premise correction must use selected Evidence IDs only")
    before = refute_premise_verdict(failing_report, gold)
    if before.satisfied:
        failures.append("the real R160 input must remain a rejected negative example")

    agent = ReporterAgent(domain_pack=domain_pack)
    if bypass_filter:
        agent.domain_pack.line_adopts_contradicted_premise = lambda *_args: False  # type: ignore[method-assign]
    ref_map = build_footnote_maps(state.evidence_store).evidence_id_to_footnote
    repaired = agent._enforce_premise_assessment(failing_report, assessment, ref_map)
    verdict = refute_premise_verdict(repaired, gold)
    if not verdict.satisfied:
        failures.append("repaired R160 report must satisfy refute_premise")
    if "## 前提核验" not in repaired:
        failures.append("the correction must be reader-visible")

    unresolved = domain_pack.assess_premise(
        "研究甲公司2024年的全球排名。",
        [state.evidence_store[0]],
        [state.report_evidence_selections[0].model_copy(update={"evidence_ids": [state.evidence_store[0].id]})],
    )
    neutral = "# 报告\n\n## 摘要\n甲公司位列第一。"
    neutral_result = agent._enforce_premise_assessment(neutral, unresolved, ref_map)
    if overclaim_unresolved:
        neutral_result += "\n\n## 前提核验\n- 题目前提不成立。"
    if neutral_result != neutral:
        failures.append("unresolved topics must not receive a fabricated refutation")
    return failures


def _self_test() -> None:
    if evaluate():
        raise SystemExit("premise_reporting_self_test=FAIL shipped implementation")
    cases = {
        "bypass_assertion_filter": evaluate(bypass_filter=True),
        "refute_unresolved_topic": evaluate(overclaim_unresolved=True),
    }
    missed = [name for name, failures in cases.items() if not failures]
    if missed:
        raise SystemExit(f"premise_reporting_self_test=FAIL missed={missed}")
    print(f"premise_reporting_self_test=PASS cases={len(cases)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        _self_test()
    failures = evaluate()
    for failure in failures:
        print(f"premise_reporting_error: {failure}", file=sys.stderr)
    print(f"premise_reporting={'PASS' if not failures else 'FAIL'} failures={len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
