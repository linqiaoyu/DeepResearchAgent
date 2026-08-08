from __future__ import annotations

import unittest
from datetime import date

from deepresearch_agent.agents import ReporterAgent
from deepresearch_agent.schemas import (
    Evidence,
    NumericFields,
    ReportClaim,
    ReportDraft,
    ReportSection,
    ResearchPlan,
    ResearchState,
    SubQuestion,
)


class ReportReaderGuardTests(unittest.TestCase):
    def test_llm_reader_render_normalizes_and_deduplicates_facts(self) -> None:
        state = ResearchState(topic="宁德时代 20241231 业绩")
        state.plan = ResearchPlan(
            topic=state.topic,
            sub_questions=[
                SubQuestion(
                    id="finance",
                    question="宁德时代 20241231 业绩意味着什么？",
                    search_queries=["fixture"],
                )
            ],
        )
        state.evidence_store = [
            self._evidence(
                state,
                "yuan",
                "营业收入",
                362_013_000_000,
                "元",
            ),
            self._evidence(
                state,
                "yi",
                "营收",
                3620.13,
                "亿元",
            ),
            Evidence(
                id="meaning",
                research_id=state.research_id,
                sub_question_id="finance",
                claim="收入下降与利润增长并存，需结合毛利率变化解释。",
                claim_type="fact",
                source_url="https://example.com/meaning",
                source_title="Meaning",
                source_pub_date=date(2025, 3, 15),
                extract_text="收入下降与利润增长并存。",
            ),
            Evidence(
                id="factory",
                research_id=state.research_id,
                sub_question_id="finance",
                claim="匈牙利工厂仍处于建设阶段。",
                claim_type="fact",
                source_url="https://example.com/factory",
                source_title="Factory",
                source_pub_date=date(2025, 3, 15),
                extract_text="匈牙利工厂仍处于建设阶段。",
            ),
        ]
        draft = ReportDraft(
            summary="截至20241231，研究使用本地证据。",
            key_findings=[
                ReportClaim(
                    text="宁德时代 20241231 营业收入为3.62013e+11元。",
                    evidence_ids=["yuan"],
                ),
                ReportClaim(
                    text="宁德时代2024年营业收入为3620.13亿元。",
                    evidence_ids=["yi"],
                ),
            ],
            detailed_analysis=[
                ReportSection(
                    sub_question_id="finance",
                    heading="含义",
                    claims=[
                        ReportClaim(
                            text="宁德时代营业收入为3620.13亿元。",
                            evidence_ids=["yi"],
                        ),
                        ReportClaim(
                            text="收入下降与利润增长并存，需结合毛利率变化解释。",
                            evidence_ids=["yuan", "meaning"],
                        ),
                        ReportClaim(
                            text="匈牙利工厂仍处于建设阶段。",
                            evidence_ids=["factory"],
                        ),
                    ],
                )
            ],
        )

        report, invalid, backfilled = ReporterAgent()._render_llm_report(
            state,
            draft,
        )
        body = report.split("## 参考来源", 1)[0]

        self.assertEqual(invalid, 0)
        self.assertEqual(backfilled, 0)
        self.assertNotRegex(body, r"\d(?:\.\d+)?e[+-]?\d+")
        self.assertNotIn("20241231", body)
        self.assertEqual(body.count("3620.13亿元"), 1)
        self.assertIn("2024年12月31日", body)
        self.assertIn("收入下降与利润增长并存", body)
        detailed = body.split("## 详细分析", 1)[1].split(
            "## 补充事实",
            1,
        )[0]
        supplemental = body.split("## 补充事实", 1)[1].split(
            "## 风险与限制",
            1,
        )[0]
        self.assertIn("收入下降与利润增长并存", detailed)
        self.assertNotIn("匈牙利工厂", detailed)
        self.assertIn("匈牙利工厂", supplemental)
        self.assertEqual(
            state.evidence_store[0].numeric_fields.value,
            362_013_000_000,
        )

    def test_every_draft_analysis_claim_is_accounted_for(self) -> None:
        """R099: a zero must say which branch consumed the claims.

        R098's A-share run delivered `reader_analysis_lines=0` with a reporter
        that had *not* fallen back, and nothing recorded whether the draft
        arrived empty or this renderer discarded it -- so the cause could only be
        guessed at by reading the function. The fixture below exercises three
        different outcomes for three claims: one renders, one is dropped as a
        restatement of a key finding's number, one falls through to 补充事实.
        """

        reporter = ReporterAgent()
        state, draft = self._three_outcome_fixture()

        reporter._render_llm_report(state, draft)
        flow = reporter.last_stats["analysis_flow"]

        self.assertEqual(flow["draft_sections"], 1)
        self.assertEqual(flow["draft_claims"], 3)
        self.assertEqual(flow["rendered_lines"], 1)
        self.assertEqual(flow["claims_dropped_duplicate_number"], 1)
        self.assertEqual(flow["claims_dropped_unrelated"], 1)
        self.assertEqual(flow["sections_unmatched_to_plan"], 0)
        self.assertEqual(flow["claims_over_section_cap"], 0)
        self._assert_counters_close(flow)

    def test_sections_sharing_a_sub_question_id_all_reach_the_reader(self) -> None:
        """R099: three sections under one id lost two of them before rendering.

        `prompts/reporter.md` asks for analysis that explains support,
        implications and limits, and the live run answered a single-sub-question
        plan with three themed sections -- all carrying the same
        `sub_question_id`, because that is the only id there is. The renderer
        keyed a dict by that id, so two of the three were discarded by the
        comprehension before any relatedness rule was applied, and the reader
        received `## 详细分析` not at all.
        """

        reporter = ReporterAgent()
        state, draft = self._three_outcome_fixture()
        renderable = draft.detailed_analysis[0].claims[1]
        draft = draft.model_copy(
            update={
                "detailed_analysis": [
                    ReportSection(
                        sub_question_id="finance",
                        heading="含义",
                        claims=[renderable],
                    ),
                    ReportSection(
                        sub_question_id="finance",
                        heading="影响",
                        claims=[
                            ReportClaim(
                                text="毛利率变化需与营业收入一并解读。",
                                evidence_ids=["yuan", "meaning"],
                            )
                        ],
                    ),
                ]
            }
        )

        report, _, _ = reporter._render_llm_report(state, draft)
        flow = reporter.last_stats["analysis_flow"]
        body = report.split("## 参考来源", 1)[0]
        # Split on the newline too: "### " contains "## ", so splitting on the
        # bare marker ends the section at its own first heading.
        analysis = body.split("## 详细分析", 1)[1].split("\n## ", 1)[0]
        cited_lines = [
            line
            for line in analysis.splitlines()
            if line.strip().startswith("- ") and "[^" in line
        ]

        self.assertEqual(flow["draft_sections"], 2)
        self.assertEqual(flow["sections_merged_by_shared_id"], 1)
        self.assertEqual(flow["rendered_lines"], 2)
        self.assertEqual(len(cited_lines), 2)
        self.assertIn("收入下降与利润增长并存", analysis)
        self.assertIn("毛利率变化需与营业收入一并解读", analysis)
        self._assert_counters_close(flow)

    def _assert_counters_close(self, flow: dict) -> None:
        """A claim that disappears without landing in a bucket is the loss itself."""

        self.assertEqual(
            flow["draft_claims"],
            flow["rendered_lines"]
            + flow["claims_dropped_duplicate_number"]
            + flow["claims_dropped_unrelated"]
            + flow["claims_over_section_cap"]
            + flow["claims_in_unmatched_sections"],
        )

    def test_a_section_the_plan_never_asked_for_is_named_not_silently_dropped(
        self,
    ) -> None:
        """R099: `by_section` is keyed by sub-question id, so a mismatch renders nothing."""

        reporter = ReporterAgent()
        state, draft = self._three_outcome_fixture()
        draft = draft.model_copy(
            update={
                "detailed_analysis": [
                    draft.detailed_analysis[0].model_copy(
                        update={"sub_question_id": "not-in-the-plan"}
                    )
                ]
            }
        )

        reporter._render_llm_report(state, draft)
        flow = reporter.last_stats["analysis_flow"]

        self.assertEqual(flow["draft_claims"], 3)
        self.assertEqual(flow["rendered_lines"], 0)
        self.assertEqual(flow["sections_unmatched_to_plan"], 1)
        self.assertEqual(flow["claims_in_unmatched_sections"], 3)
        self._assert_counters_close(flow)

    def _three_outcome_fixture(self) -> tuple[ResearchState, ReportDraft]:
        state = ResearchState(topic="宁德时代 20241231 业绩")
        state.plan = ResearchPlan(
            topic=state.topic,
            sub_questions=[
                SubQuestion(
                    id="finance",
                    question="宁德时代 20241231 业绩意味着什么？",
                    search_queries=["fixture"],
                )
            ],
        )
        state.evidence_store = [
            self._evidence(state, "yuan", "营业收入", 362_013_000_000, "元"),
            self._evidence(state, "yi", "营收", 3620.13, "亿元"),
            Evidence(
                id="meaning",
                research_id=state.research_id,
                sub_question_id="finance",
                claim="收入下降与利润增长并存，需结合毛利率变化解释。",
                claim_type="fact",
                source_url="https://example.com/meaning",
                source_title="Meaning",
                source_pub_date=date(2025, 3, 15),
                extract_text="收入下降与利润增长并存。",
            ),
            Evidence(
                id="factory",
                research_id=state.research_id,
                sub_question_id="finance",
                claim="匈牙利工厂仍处于建设阶段。",
                claim_type="fact",
                source_url="https://example.com/factory",
                source_title="Factory",
                source_pub_date=date(2025, 3, 15),
                extract_text="匈牙利工厂仍处于建设阶段。",
            ),
        ]
        draft = ReportDraft(
            summary="截至20241231，研究使用本地证据。",
            key_findings=[
                ReportClaim(
                    text="宁德时代 20241231 营业收入为3.62013e+11元。",
                    evidence_ids=["yuan"],
                ),
                ReportClaim(
                    text="宁德时代2024年营业收入为3620.13亿元。",
                    evidence_ids=["yi"],
                ),
            ],
            detailed_analysis=[
                ReportSection(
                    sub_question_id="finance",
                    heading="含义",
                    claims=[
                        ReportClaim(
                            text="宁德时代营业收入为3620.13亿元。",
                            evidence_ids=["yi"],
                        ),
                        ReportClaim(
                            text="收入下降与利润增长并存，需结合毛利率变化解释。",
                            evidence_ids=["yuan", "meaning"],
                        ),
                        ReportClaim(
                            text="匈牙利工厂仍处于建设阶段。",
                            evidence_ids=["factory"],
                        ),
                    ],
                )
            ],
        )
        return state, draft

    def _evidence(
        self,
        state: ResearchState,
        evidence_id: str,
        metric: str,
        value: float,
        unit: str,
    ) -> Evidence:
        return Evidence(
            id=evidence_id,
            research_id=state.research_id,
            sub_question_id="finance",
            claim=f"宁德时代 2024 年累计营业收入为 {value} {unit}。",
            claim_type="data",
            source_url=f"https://example.com/{evidence_id}",
            source_title=evidence_id,
            source_pub_date=date(2025, 3, 15),
            extract_text="fixture",
            numeric_fields=NumericFields(
                entity="宁德时代",
                metric_name=metric,
                period="20241231",
                dimension="累计",
                value=value,
                unit=unit,
            ),
        )


if __name__ == "__main__":
    unittest.main()
