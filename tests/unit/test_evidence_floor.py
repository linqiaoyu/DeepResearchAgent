"""R116: a sub-question with Evidence may not reach the reader as silence.

The reporter model receives every packed Evidence item and writes the draft that
becomes the report, so a sub-question it passes over is lost entirely. On the 30
R113 live reports that happened to 8 of 80 sub-questions, and it is how the four
figures refuting Q16's false premise were retrieved, extracted, packed into the
reporter's context, and never printed.
"""

from __future__ import annotations

import importlib.util
import unittest
from typing import Any

from deepresearch_agent.agents.reporter import (
    MAX_EVIDENCE_FLOOR_CLAIMS,
    ReporterAgent,
)
from deepresearch_agent.citations import build_footnote_maps
from deepresearch_agent.reporting.reader_reach import (
    evidence_the_reader_can_follow,
    orphaned_sub_questions,
)
from deepresearch_agent.schemas import (
    Evidence,
    ReportClaim,
    ReportDraft,
    ReportSection,
    ResearchPlan,
    ResearchState,
    Source,
    SubQuestion,
)
from deepresearch_agent.settings import project_root

RESEARCH_ID = "evidence-floor"


def _guard() -> Any:
    spec = importlib.util.spec_from_file_location(
        "check_evidence_reaches_reader",
        project_root() / "scripts" / "check_evidence_reaches_reader.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _source(name: str) -> Source:
    return Source(
        id=f"src-{name}",
        title=f"{name} source",
        url=f"https://example.invalid/{name}",
        source_type="web",
        content=name,
    )


def _evidence(name: str, sub_question_id: str, claim: str, confidence: float) -> Evidence:
    source = _source(name)
    return Evidence(
        id=f"ev-{name}",
        research_id=RESEARCH_ID,
        sub_question_id=sub_question_id,
        claim=claim,
        claim_type="fact",
        source_title=source.title,
        source_url=source.url,
        extract_text=claim,
        confidence=confidence,
    )


def _state(evidence: list[Evidence], sub_question_ids: list[str]) -> ResearchState:
    state = ResearchState(topic="evidence floor", research_id=RESEARCH_ID)
    state.plan = ResearchPlan(
        topic="evidence floor",
        sub_questions=[
            SubQuestion(id=item, question=f"question {item}", search_queries=[item])
            for item in sub_question_ids
        ],
    )
    state.sources = [_source(item.id.removeprefix("ev-")) for item in evidence]
    state.evidence_store = evidence
    state.report_footnote_evidence = {
        number: item.id
        for number, item in build_footnote_maps(evidence).footnote_to_evidence.items()
    }
    return state


def _render(state: ResearchState, draft: ReportDraft) -> str:
    report, _invalid, _backfills = ReporterAgent()._render_llm_report(state, draft)
    return report


class EvidenceFloorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.answered = _evidence("answered", "answered", "The answered claim.", 0.9)
        self.passed_over = _evidence(
            "passedover", "ignored", "The evidence the draft never cites.", 0.8
        )
        self.state = _state([self.answered, self.passed_over], ["answered", "ignored"])
        self.draft = ReportDraft(
            summary="Only the first sub-question is written up.",
            key_findings=[
                ReportClaim(text="The answered claim.", evidence_ids=["ev-answered"])
            ],
            detailed_analysis=[
                ReportSection(
                    sub_question_id="answered",
                    heading="answered",
                    claims=[
                        ReportClaim(
                            text="The answered claim.", evidence_ids=["ev-answered"]
                        )
                    ],
                )
            ],
            risks=[],
            unverified_assumptions=[],
        )

    def test_evidence_the_draft_ignored_still_reaches_the_reader(self) -> None:
        report = _render(self.state, self.draft)
        self.assertIn("The evidence the draft never cites.", report)

    def test_the_floor_leaves_no_orphaned_sub_question(self) -> None:
        report = _render(self.state, self.draft)
        self.assertEqual(orphaned_sub_questions(self.state, report), [])

    def test_removing_the_floor_reintroduces_the_orphan(self) -> None:
        """Deleting the floor call must fail, not silently shrink the report."""

        original = ReporterAgent._render_evidence_floor
        try:
            ReporterAgent._render_evidence_floor = (  # type: ignore[method-assign]
                lambda *args, **kwargs: ([], 0)
            )
            report = _render(self.state, self.draft)
        finally:
            ReporterAgent._render_evidence_floor = original  # type: ignore[method-assign]
        self.assertNotIn("The evidence the draft never cites.", report)
        self.assertEqual(
            orphaned_sub_questions(self.state, report), [("ignored", 1)]
        )

    def test_the_floor_does_not_repeat_a_sub_question_the_draft_covered(self) -> None:
        """One 详细分析 section for `answered`: the draft's, not a floor copy."""

        report = _render(self.state, self.draft)
        self.assertEqual(report.count("### question answered"), 1)
        reporter = ReporterAgent()
        reporter._render_llm_report(self.state, self.draft)
        self.assertEqual(
            reporter.last_stats["analysis_flow"]["evidence_floor_sub_questions"], 1
        )

    def test_a_sub_question_with_no_evidence_gets_no_floor_section(self) -> None:
        state = _state([self.answered], ["answered", "empty"])
        report = _render(state, self.draft)
        self.assertNotIn("question empty", report)

    def test_the_floor_is_bounded(self) -> None:
        items = [
            _evidence(f"extra{index}", "ignored", f"Extra claim {index}.", 0.5 + index / 100)
            for index in range(MAX_EVIDENCE_FLOOR_CLAIMS + 3)
        ]
        state = _state([self.answered, *items], ["answered", "ignored"])
        report = _render(state, self.draft)
        rendered = sum(1 for item in items if item.claim in report)
        self.assertEqual(rendered, MAX_EVIDENCE_FLOOR_CLAIMS)

    def test_the_floor_prefers_the_highest_confidence_evidence(self) -> None:
        low = _evidence("low", "ignored", "Low confidence claim.", 0.30)
        high = _evidence("high", "ignored", "High confidence claim.", 0.95)
        state = _state([self.answered, low, high], ["answered", "ignored"])
        report = _render(state, self.draft)
        self.assertIn("High confidence claim.", report)

    def test_the_floor_is_deterministic_across_evidence_order(self) -> None:
        """Which claims the floor picks, and their order, do not depend on input order.

        Footnote *numbers* do -- `build_footnote_maps` numbers by Evidence
        order -- so this asserts the floor's own output, not that builder's.
        """

        low = _evidence("low", "ignored", "Low confidence claim.", 0.30)
        high = _evidence("high", "ignored", "High confidence claim.", 0.95)

        def floor_claims(evidence: list[Evidence]) -> list[str]:
            report = _render(_state(evidence, ["answered", "ignored"]), self.draft)
            section = report.split("### question ignored")[1].split("\n##")[0]
            return [
                line.split(" [^")[0].removeprefix("- ")
                for line in section.splitlines()
                if line.startswith("- ")
            ]

        self.assertEqual(
            floor_claims([self.answered, low, high]),
            floor_claims([self.answered, high, low]),
        )
        self.assertEqual(
            floor_claims([self.answered, low, high]),
            ["High confidence claim.", "Low confidence claim."],
        )

    def test_floor_lines_are_counted_for_the_run_record(self) -> None:
        reporter = ReporterAgent()
        reporter._render_llm_report(self.state, self.draft)
        flow = reporter.last_stats["analysis_flow"]
        self.assertEqual(flow["evidence_floor_sub_questions"], 1)
        self.assertEqual(flow["evidence_floor_lines"], 1)

    def test_floor_lines_are_cited(self) -> None:
        """A floor line asserts a fact, so it carries its footnote."""

        report = _render(self.state, self.draft)
        line = next(
            item
            for item in report.splitlines()
            if "The evidence the draft never cites." in item
        )
        self.assertRegex(line, r"\[\^\d+\]")


class ReaderReachabilityTests(unittest.TestCase):
    def test_an_uncited_footnote_definition_is_not_reachable(self) -> None:
        """83% of R113 reference lines were never cited; definitions do not count."""

        evidence = [_evidence("only", "one", "A claim.", 0.9)]
        state = _state(evidence, ["one"])
        report = "## 摘要\n无。\n\n## 参考来源\n[^1]: x. https://example.invalid/only\n"
        self.assertEqual(evidence_the_reader_can_follow(state, report), set())

    def test_siblings_behind_one_footnote_are_reachable(self) -> None:
        """R107 gives one footnote to every Evidence sharing a source URL."""

        first = _evidence("shared", "one", "First sentence.", 0.9)
        second = Evidence(
            id="ev-sibling",
            research_id=RESEARCH_ID,
            sub_question_id="one",
            claim="Second sentence from the same source.",
            claim_type="fact",
            source_title=first.source_title,
            source_url=first.source_url,
            extract_text="Second sentence from the same source.",
            confidence=0.7,
        )
        state = _state([first, second], ["one"])
        report = "## 摘要\n见 [^1]。\n\n## 参考来源\n[^1]: x. https://example.invalid/shared\n"
        self.assertEqual(
            evidence_the_reader_can_follow(state, report),
            {"ev-shared", "ev-sibling"},
        )

    def test_self_test_passes(self) -> None:
        self.assertEqual(_guard()._self_test(), 0)


if __name__ == "__main__":
    unittest.main()


class FloorClaimTextTests(unittest.TestCase):
    """R116: the typed re-rendering must not delete a claim's analysis.

    `_evidence_claim_text` replaces a data claim with its typed fields so a
    paraphrase can never display a wrong value. On the R113 Q08 state that
    turned 「2024年贵州茅台营业总收入为1741.44亿元，同比增长15.66%，未出现下滑。」
    into a bare value: the number survived, the year-on-year and the refutation
    of the question's premise did not.
    """

    def _data_evidence(self, claim: str, value: str) -> Evidence:
        from decimal import Decimal

        from deepresearch_agent.schemas import NumericFields

        return Evidence(
            id="ev-data",
            research_id=RESEARCH_ID,
            sub_question_id="one",
            claim=claim,
            claim_type="data",
            source_title="source",
            source_url="https://example.invalid/data",
            extract_text=claim,
            confidence=0.95,
            numeric_fields=NumericFields(
                entity="E", metric_name="M", period="2024",
                value=Decimal(value), unit="亿元",
            ),
        )

    def test_a_claim_agreeing_with_the_typed_value_is_shown_as_extracted(self) -> None:
        item = self._data_evidence(
            "2024年营业总收入为1741.44亿元，同比增长15.66%，未出现下滑。", "1741.44"
        )
        self.assertEqual(ReporterAgent()._floor_claim_text(item), item.claim)

    def test_a_claim_disagreeing_with_the_typed_value_falls_back_to_typed(self) -> None:
        item = self._data_evidence("2024年营业总收入为9999.99亿元。", "1741.44")
        rendered = ReporterAgent()._floor_claim_text(item)
        self.assertNotEqual(rendered, item.claim)
        self.assertNotIn("9999.99", rendered)

    def test_a_claim_quoting_the_value_in_raw_units_still_agrees(self) -> None:
        item = self._data_evidence(
            "营业总收入为174,144,000,000元，同比增长15.66%。", "1741.44"
        )
        self.assertEqual(ReporterAgent()._floor_claim_text(item), item.claim)


class FloorRankingTests(unittest.TestCase):
    """R116: confidence ranks provider trust, not relevance to the question.

    Every structured row carries 0.98 and every extracted sentence 0.85--0.95,
    so on the R113 Q16 state a market-share question's floor was two net-profit
    rows while the share figures sat below them.
    """

    def test_an_item_answering_the_question_outranks_a_more_confident_one(self) -> None:
        answering = Evidence(
            id="ev-answering",
            research_id=RESEARCH_ID,
            sub_question_id="ignored",
            claim="全球动力电池装机量市场份额排名第一。",
            claim_type="fact",
            source_title="share",
            source_url="https://example.invalid/share",
            extract_text="share",
            confidence=0.85,
        )
        unrelated = Evidence(
            id="ev-unrelated",
            research_id=RESEARCH_ID,
            sub_question_id="ignored",
            claim="归母净利润为300亿元。",
            claim_type="fact",
            source_title="profit",
            source_url="https://example.invalid/profit",
            extract_text="profit",
            confidence=0.98,
        )
        answered = _evidence("answered", "answered", "The answered claim.", 0.9)
        state = ResearchState(topic="rank", research_id=RESEARCH_ID)
        state.plan = ResearchPlan(
            topic="rank",
            sub_questions=[
                SubQuestion(id="answered", question="q", search_queries=["q"]),
                SubQuestion(
                    id="ignored",
                    question="全球动力电池装机量市场份额排名是怎样的？",
                    search_queries=["share"],
                ),
            ],
        )
        state.sources = [_source("answered"), _source("share"), _source("profit")]
        state.evidence_store = [answered, unrelated, answering]
        state.report_footnote_evidence = {
            number: item.id
            for number, item in build_footnote_maps(
                state.evidence_store
            ).footnote_to_evidence.items()
        }
        draft = ReportDraft(
            summary="s",
            key_findings=[
                ReportClaim(text="The answered claim.", evidence_ids=["ev-answered"])
            ],
            detailed_analysis=[],
            risks=[],
            unverified_assumptions=[],
        )
        report = _render(state, draft)
        section = report.split("### 全球动力电池装机量市场份额排名是怎样的？")[1]
        first = next(
            line for line in section.splitlines() if line.startswith("- ")
        )
        self.assertIn("市场份额排名第一", first)


class ReferencePruneTests(unittest.TestCase):
    """R118: the first live run under R117 shipped markers with no reference.

    R117 filtered the reference list inside the two renderers, which is one step
    too early: `_append_metric_coverage` adds a section *after* the reference
    list is written, and the delivered page cited `[^1]` and `[^4]` from
    指标覆盖状态 with neither defined. The gate missed it because the demo topic
    requests no metrics and never renders that section.
    """

    def test_a_reference_cited_only_below_the_heading_is_kept(self) -> None:
        from deepresearch_agent.agents.reporter import prune_reference_list

        report = (
            "## 摘要\n见 [^2]。\n\n## 参考来源\n"
            "[^1]: A. https://a.invalid\n[^2]: B. https://b.invalid\n"
            "\n## 指标覆盖状态\n- 值 [^1]\n"
        )
        pruned = prune_reference_list(report)
        self.assertIn("[^1]: A.", pruned)
        self.assertIn("[^2]: B.", pruned)

    def test_a_reference_nothing_cites_is_dropped(self) -> None:
        from deepresearch_agent.agents.reporter import prune_reference_list

        report = (
            "## 摘要\n见 [^2]。\n\n## 参考来源\n"
            "[^1]: A. https://a.invalid\n[^2]: B. https://b.invalid\n"
        )
        pruned = prune_reference_list(report)
        self.assertNotIn("[^1]: A.", pruned)
        self.assertIn("[^2]: B.", pruned)

    def test_a_report_without_references_is_unchanged(self) -> None:
        from deepresearch_agent.agents.reporter import prune_reference_list

        report = "## 摘要\n无引用。\n"
        self.assertEqual(prune_reference_list(report), report.rstrip("\n"))

    def test_pruning_never_orphans_a_marker(self) -> None:
        """The property the R117 regression violated, stated directly."""

        import importlib.util

        from deepresearch_agent.agents.reporter import prune_reference_list

        spec = importlib.util.spec_from_file_location(
            "check_reference_list_hygiene",
            project_root() / "scripts" / "check_reference_list_hygiene.py",
        )
        assert spec is not None and spec.loader is not None
        guard = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(guard)

        report = (
            "## 摘要\n见 [^2]。\n\n## 参考来源\n"
            "[^1]: A. https://a.invalid\n[^2]: B. https://b.invalid\n"
            "[^3]: C. https://c.invalid\n"
            "\n## 指标覆盖状态\n- 值 [^1] [^3]\n"
        )
        self.assertEqual(guard.errors_for(prune_reference_list(report)), [])
