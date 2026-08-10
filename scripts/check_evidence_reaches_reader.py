"""Refuse a report that answers a sub-question with silence.

R116. The reporter model receives every packed Evidence item and writes the
draft that becomes the report -- rendering drops nothing, so whatever the model
passes over is what the reader loses. Measured across the 30 R113 live reports:

* 2844 Evidence items were extracted and **782 (27%)** were reachable from a
  footnote the report actually cited;
* **8 of 80** sub-questions produced Evidence and had none of it reachable, so
  a question the agent researched arrived as silence, in 8 of the 30 reports;
* of the golden set's 50 numeric facts, 25 reached the reader, 12 were never
  retrieved, and **13 were retrieved, extracted, packed into the reporter's
  context, and then never printed**.

Q16 is the shape of it. Nine SNE Research items sat under `share_2024` while
the model wrote 「未获取SNE Research等第三方机构的官方装机量数据」 in its own
risk section and answered the market-share question from revenue instead. All
four figures that refute the question's false premise were in hand.

This checks the reader-visible property directly, per AGENTS.md section 8: a
sub-question with Evidence must have at least one Evidence item the reader can
follow. It does not ask whether retrieval was good, or whether citations
resolve -- both were already green on the reports above.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from deepresearch_agent.reporting.reader_reach import (  # noqa: E402
    evidence_the_reader_can_follow,
    orphaned_sub_questions,
)
from deepresearch_agent.schemas import ResearchState  # noqa: E402

def _report_for(state: ResearchState) -> str:
    if not state.final_report:
        raise SystemExit("state has no final_report")
    return state.final_report


def _self_test() -> int:
    """Render a draft that ignores a sub-question, with and without the floor.

    The negative case is the product as it behaved before R116: the model's
    draft cites one sub-question's Evidence and says nothing about the other.
    """

    from deepresearch_agent.agents.reporter import ReporterAgent
    from deepresearch_agent.schemas import (
        Evidence,
        ReportClaim,
        ReportDraft,
        ReportSection,
        ResearchPlan,
        Source,
        SubQuestion,
    )

    answered_source = Source(
        id="src-answered",
        title="Answered source",
        url="https://example.invalid/answered",
        source_type="web",
        content="answered",
    )
    ignored_source = Source(
        id="src-ignored",
        title="Market share statistics",
        url="https://example.invalid/share",
        source_type="web",
        content="share statistics",
    )
    research_id = "floor-self-test"
    answered = Evidence(
        id="ev-answered",
        research_id=research_id,
        sub_question_id="answered",
        claim="The first sub-question has a rendered answer.",
        claim_type="fact",
        source_title=answered_source.title,
        source_url=answered_source.url,
        extract_text="The first sub-question has a rendered answer.",
        confidence=0.9,
    )
    ignored = Evidence(
        id="ev-ignored",
        research_id=research_id,
        sub_question_id="ignored",
        claim="The second sub-question holds evidence the draft never cites.",
        claim_type="fact",
        source_title=ignored_source.title,
        source_url=ignored_source.url,
        extract_text="The second sub-question holds evidence the draft never cites.",
        confidence=0.8,
    )
    state = ResearchState(topic="floor self test", research_id=research_id)
    state.plan = ResearchPlan(
        topic="floor self test",
        sub_questions=[
            SubQuestion(id="answered", question="What is answered?", search_queries=["answered"]),
            SubQuestion(
                id="ignored",
                question="What is passed over?",
                search_queries=["passed over"],
            ),
        ],
    )
    state.sources = [answered_source, ignored_source]
    state.evidence_store = [answered, ignored]
    draft = ReportDraft(
        summary="A summary that mentions only the first sub-question.",
        key_findings=[
            ReportClaim(text="The first sub-question has a rendered answer.", evidence_ids=["ev-answered"])
        ],
        detailed_analysis=[
            ReportSection(
                sub_question_id="answered",
                heading="answered",
                claims=[
                    ReportClaim(
                        text="The first sub-question has a rendered answer.",
                        evidence_ids=["ev-answered"],
                    )
                ],
            )
        ],
        risks=["The second sub-question was not researched."],
        unverified_assumptions=[],
    )
    # `generate()` publishes this mapping; `_render_llm_report` is the inner
    # call, so the self test builds it the same way rather than reimplementing
    # footnote numbering (AGENTS.md section 6: consumers must not rebuild it).
    from deepresearch_agent.citations import build_footnote_maps

    state.report_footnote_evidence = {
        number: item.id
        for number, item in build_footnote_maps(
            state.evidence_store
        ).footnote_to_evidence.items()
    }
    reporter = ReporterAgent()
    report, _invalid, _backfills = reporter._render_llm_report(state, draft)
    state.final_report = report

    failures = 0
    shipped = orphaned_sub_questions(state, report)
    print(f"[self-test] with the floor: orphaned={shipped}")
    if shipped:
        print("[self-test] FAIL: the floor left a sub-question unreachable", file=sys.stderr)
        failures += 1
    if "The second sub-question holds evidence the draft never cites." not in report:
        print("[self-test] FAIL: the floor did not render the passed-over evidence", file=sys.stderr)
        failures += 1

    # The deliberate wrong implementation: a floor that renders nothing, which
    # is what shipped before R116.
    original = ReporterAgent._render_evidence_floor
    try:
        ReporterAgent._render_evidence_floor = (  # type: ignore[method-assign]
            lambda *args, **kwargs: ([], 0)
        )
        without = ReporterAgent()
        report_without, _i, _b = without._render_llm_report(state, draft)
        state_without = state.model_copy(deep=True)
        state_without.report_footnote_evidence = without.last_stats.get(
            "footnote_evidence", state.report_footnote_evidence
        )
        orphans_without = orphaned_sub_questions(state, report_without)
        print(f"[self-test] floor disabled: orphaned={orphans_without}")
        if not orphans_without:
            print(
                "[self-test] FAIL: disabling the floor was not detected; "
                "the check cannot see the defect it exists for",
                file=sys.stderr,
            )
            failures += 1
    finally:
        ReporterAgent._render_evidence_floor = original  # type: ignore[method-assign]

    print(f"evidence_reaches_reader_self_test={'PASS' if not failures else 'FAIL'} cases=3")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--state", type=Path, help="a saved ResearchState json")
    parser.add_argument("--report", type=Path, help="the delivered report; defaults to state.final_report")
    args = parser.parse_args()

    if args.self_test:
        return _self_test()
    if args.state is None:
        parser.error("choose --self-test or --state")

    payload: Any = json.loads(args.state.read_text(encoding="utf-8"))
    state = ResearchState.model_validate(payload)
    report = args.report.read_text(encoding="utf-8") if args.report else _report_for(state)
    orphans = orphaned_sub_questions(state, report)
    reachable = evidence_the_reader_can_follow(state, report)
    for sub_question_id, count in orphans:
        print(
            f"evidence_reaches_reader_error: sub-question {sub_question_id} has "
            f"{count} evidence item(s) and none the reader can follow",
            file=sys.stderr,
        )
    print(
        f"evidence_reaches_reader={'PASS' if not orphans else 'FAIL'} "
        f"sub_questions={len(state.plan.sub_questions) if state.plan else 0} "
        f"orphaned={len(orphans)} "
        f"evidence={len(state.evidence_store)} reachable={len(reachable)}"
    )
    return 1 if orphans else 0


if __name__ == "__main__":
    raise SystemExit(main())
