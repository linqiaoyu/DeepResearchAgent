from __future__ import annotations

import unittest
from datetime import date

from difflib import SequenceMatcher

from deepresearch_agent.agents import ReporterAgent
from deepresearch_agent.citations import build_footnote_maps
from deepresearch_agent.domains.registry import load_domain_pack
from deepresearch_agent.agents.reporter import (
    RESTATEMENT_SIMILARITY,
    _content_key,
    restates_an_emitted_line,
)
from deepresearch_agent.schemas import (
    MAX_REPORT_SECTION_CLAIMS,
    Evidence,
    NumericFields,
    ReportClaim,
    ReportDraft,
    ReportSection,
    ResearchPlan,
    StructuredDataRequest,
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
        self.assertEqual(flow["claims_over_section_cap"], 0)
        self.assertEqual(len(cited_lines), 2)
        self.assertIn("收入下降与利润增长并存", analysis)
        self.assertIn("毛利率变化需与营业收入一并解读", analysis)
        self._assert_counters_close(flow)

    def test_merged_sections_are_not_re_capped_as_one_section(self) -> None:
        """R099: the three-claim cap is per authored section, not per merged group.

        `ReportSection.claims` already bounds a section at three, so a validated
        draft can never exceed the cap on its own. Re-applying the same number
        after merging was therefore the only thing the cap ever cut: the second
        live run this round reached `claims_over_section_cap=3` of 6 claims that
        way, all of them inside the reporter's stated allowance.
        """

        reporter = ReporterAgent()
        state, draft = self._three_outcome_fixture()

        def qualitative(index: int) -> ReportClaim:
            return ReportClaim(
                text=f"驱动因素解释之{index}：结构性变化需结合披露口径理解。",
                evidence_ids=["yuan", "meaning"],
            )

        draft = draft.model_copy(
            update={
                "detailed_analysis": [
                    ReportSection(
                        sub_question_id="finance",
                        heading=f"主题{group}",
                        claims=[
                            qualitative(group * MAX_REPORT_SECTION_CLAIMS + item)
                            for item in range(MAX_REPORT_SECTION_CLAIMS)
                        ],
                    )
                    for group in range(2)
                ]
            }
        )

        reporter._render_llm_report(state, draft)
        flow = reporter.last_stats["analysis_flow"]

        self.assertEqual(flow["draft_claims"], 2 * MAX_REPORT_SECTION_CLAIMS)
        self.assertEqual(flow["claims_over_section_cap"], 0)
        # Every claim the reporter was allowed to write reaches the reader.
        self.assertEqual(flow["rendered_lines"], 2 * MAX_REPORT_SECTION_CLAIMS)
        self._assert_counters_close(flow)

    def test_analysis_about_an_already_stated_metric_survives(self) -> None:
        """R100: the repeat test must separate restating from explaining.

        `prompts/reporter.md` tells the reporter not to repeat a key finding
        verbatim; the renderer enforced `\\d`, true of any sentence carrying a
        year. For a financial question every analysis line names the metric the
        key findings already state, so the rule deleted the analysis and kept
        nothing in its place -- 2 of 3 claims in R099's last live run.
        """

        emitted = ["宁德时代 2024年12月31日 营业收入为3620.13亿元。 [^1]"]

        restatements = [
            "宁德时代营业收入为3620.13亿元。",
            "宁德时代2024年营业收入为3620.13亿元。",
        ]
        analysis = [
            "2024年营业收入3620.13亿元的增长主要来自动力电池出货量提升，而非单价上行。",
            "营业收入口径包含储能业务，与分部报表的电池收入不可直接比较。",
            "收入下降与利润增长并存，需结合毛利率变化解释。",
        ]

        for text in restatements:
            self.assertTrue(
                restates_an_emitted_line(text, emitted),
                f"a bare restatement reached the reader twice: {text}",
            )
        for text in analysis:
            self.assertFalse(
                restates_an_emitted_line(text, emitted),
                f"an explanatory line was deleted as a repeat: {text}",
            )

    def test_the_repeat_threshold_is_not_on_a_knife_edge(self) -> None:
        """The two populations must sit either side of it with room to spare."""

        emitted = ["宁德时代 2024年12月31日 营业收入为3620.13亿元。 [^1]"]
        key = _content_key(emitted[0])

        def ratio(text: str) -> float:
            return SequenceMatcher(None, _content_key(text), key).ratio()

        restatement = ratio("宁德时代营业收入为3620.13亿元。")
        explanation = ratio(
            "2024年营业收入3620.13亿元的增长主要来自动力电池出货量提升，而非单价上行。"
        )

        self.assertGreaterEqual(restatement, RESTATEMENT_SIMILARITY + 0.05)
        self.assertLessEqual(explanation, RESTATEMENT_SIMILARITY - 0.2)

    def test_dropped_analysis_claims_are_recorded_with_their_text(self) -> None:
        """R100: a counter says how many; judging the rule needs which."""

        reporter = ReporterAgent()
        state, draft = self._three_outcome_fixture()

        reporter._render_llm_report(state, draft)
        dropped = reporter.last_stats["dropped_analysis_claims"]

        self.assertEqual(
            [item["reason"] for item in dropped],
            ["duplicate_number", "unrelated"],
        )
        self.assertIn("3620.13", dropped[0]["text"])
        self.assertIn("匈牙利工厂", dropped[1]["text"])

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


class AnalysisTopicalityTests(unittest.TestCase):
    """R100: what makes an analysis claim on topic when nothing is grounded."""

    def test_a_claim_naming_the_metric_is_on_topic_without_shared_evidence(self) -> None:
        """The four claims R100's live run deleted all named the question's metrics.

        Relatedness was decided by whether a claim cited a key finding's
        evidence. Every required metric came back a gap in that run, so the
        reader's `关键发现` cited nothing at all and there was no evidence to
        share -- four claims about this question's own revenue and margin
        drivers were filed as off-topic and deleted with `补充事实`.
        """

        finance = load_domain_pack("finance")
        required = {"营业收入", "主营业务毛利率"}
        deleted_by_that_rule = [
            "2023年6月蔚来全系降价3万元，带动交付量在第三季度回升，对全年营收形成支撑。",
            "2024年营收和交付量均创历史新高，延续增长态势。",
            "2023年第四季度整车毛利率为11.9%，连续两个季度达到两位数，显示毛利率逐步修复。",
            "李斌表示新产品主要承担走量任务，NIO品牌则负责确保毛利率，体现双品牌策略。",
        ]

        for text in deleted_by_that_rule:
            self.assertTrue(
                finance.metrics_mentioned(text, required),
                f"an on-topic driver was filed as off-topic: {text}",
            )

    def test_a_claim_naming_no_required_metric_stays_off_topic(self) -> None:
        finance = load_domain_pack("finance")
        required = {"营业收入", "主营业务毛利率"}

        self.assertEqual(
            finance.metrics_mentioned("匈牙利工厂仍处于建设阶段。", required),
            set(),
        )

    def test_a_domain_without_a_metric_vocabulary_claims_nothing(self) -> None:
        from deepresearch_agent.domains.null import NullDomainPack

        self.assertEqual(
            NullDomainPack().metrics_mentioned("anything at all", {"revenue"}),
            set(),
        )


class NumericFidelityTests(unittest.TestCase):
    """R100: the guard must not delete a claim that quotes its own source."""

    def _evidence(self, text: str) -> Evidence:
        return Evidence(
            id="e1",
            research_id="r",
            sub_question_id="s",
            claim=text,
            claim_type="fact",
            source_url="https://example.com/a",
            source_title="t",
            extract_text=text,
        )

    def _policy(self):
        return load_domain_pack("finance").numeric_citation_policy()

    def test_a_margin_claim_quoting_its_evidence_word_for_word_is_supported(self) -> None:
        """R100's live run deleted exactly this pair.

        The claim's generic `毛利率` was rescoped to `主营业务毛利率` whenever that
        metric was required, while the evidence side rescopes only when a typed
        total-row field anchors it -- which retrieved web text never carries. The
        two sides were then compared under different names.
        """

        evidence = [self._evidence("2024年蔚来的汽车毛利率为12.3%，同比增加2.8个百分点")]
        claim = "2024年汽车毛利率提升至12.3%，同比增加2.8个百分点，主要因单位物料成本下降。"

        self.assertFalse(
            self._policy().has_numeric_mismatch(
                claim, evidence, required_metrics={"营业收入", "主营业务毛利率"}
            )
        )

    def test_a_number_the_evidence_never_states_is_still_rejected(self) -> None:
        evidence = [self._evidence("2024年蔚来的汽车毛利率为12.3%，同比增加2.8个百分点")]
        claim = "2024年汽车毛利率提升至18.9%。"

        self.assertTrue(
            self._policy().has_numeric_mismatch(
                claim, evidence, required_metrics={"营业收入", "主营业务毛利率"}
            )
        )

    def test_a_prior_year_level_after_a_comparison_word_is_not_a_change(self) -> None:
        """`较2022年的10.4%` names last year's margin, not this year's change.

        The same construction was already handled for amounts -- `较2024年的
        1,708.99亿元` -- and the rule simply did not cover a rate, so a claim
        whose every number its evidence states was rejected and the reader lost
        the line.
        """

        evidence = [self._evidence("2023年公司毛利率为5.5%，2022年为10.4%")]
        claim = "2023年公司毛利率为5.5%，较2022年的10.4%下降4.9个百分点。"

        self.assertFalse(
            self._policy().has_numeric_mismatch(
                claim, evidence, required_metrics={"营业收入", "主营业务毛利率"}
            )
        )

    def test_a_change_after_a_comparison_word_is_still_supported(self) -> None:
        evidence = [self._evidence("2023年公司毛利率为5.5%，2022年为10.4%")]
        claim = "2023年公司毛利率为5.5%，较2022年下降4.9个百分点。"

        self.assertFalse(
            self._policy().has_numeric_mismatch(
                claim, evidence, required_metrics={"营业收入", "主营业务毛利率"}
            )
        )

    def test_a_margin_the_evidence_never_states_is_rejected(self) -> None:
        evidence = [self._evidence("2023年公司毛利率为5.5%，2022年为10.4%")]

        self.assertTrue(
            self._policy().has_numeric_mismatch(
                "2023年公司毛利率为9.9%。",
                evidence,
                required_metrics={"营业收入", "主营业务毛利率"},
            )
        )


class AnalysisReachesTheReaderTests(unittest.TestCase):
    """R100 end to end: an on-topic driver survives the whole render path."""

    def _state(self) -> ResearchState:
        state = ResearchState(topic="蔚来 2023 与 2024 年营收和毛利率的变化及其驱动因素")
        state.plan = ResearchPlan(
            topic=state.topic,
            sub_questions=[
                SubQuestion(
                    id="rev_gm_values",
                    question="蔚来 2023 与 2024 年营收和毛利率如何变化？",
                    search_queries=["fixture"],
                    structured_data_requests=[
                        StructuredDataRequest(
                            capability="financial_indicators",
                            symbol="NIO",
                            metrics=["营业收入", "主营业务毛利率"],
                            periods=["20231231", "20241231"],
                        )
                    ],
                )
            ],
        )
        state.evidence_store = [
            Evidence(
                id="anchor",
                research_id=state.research_id,
                sub_question_id="rev_gm_values",
                claim="蔚来2024年营业收入为657.3亿元。",
                claim_type="data",
                source_url="https://example.com/anchor",
                source_title="Anchor",
                source_pub_date=date(2025, 3, 21),
                extract_text="蔚来2024年营业收入为657.3亿元。",
            ),
            Evidence(
                id="driver",
                research_id=state.research_id,
                sub_question_id="rev_gm_values",
                claim="2023年6月蔚来全系降价3万元，带动交付量回升，对全年营收形成支撑。",
                claim_type="fact",
                source_url="https://example.com/driver",
                source_title="Driver",
                source_pub_date=date(2025, 3, 21),
                extract_text="2023年6月蔚来全系降价3万元，带动交付量回升，对全年营收形成支撑。",
            ),
            Evidence(
                id="offtopic",
                research_id=state.research_id,
                sub_question_id="rev_gm_values",
                claim="匈牙利工厂仍处于建设阶段。",
                claim_type="fact",
                source_url="https://example.com/offtopic",
                source_title="Offtopic",
                source_pub_date=date(2025, 3, 21),
                extract_text="匈牙利工厂仍处于建设阶段。",
            ),
        ]
        return state

    def test_a_driver_citing_no_key_finding_evidence_still_reaches_the_reader(
        self,
    ) -> None:
        """The exact shape R100's live run deleted four times.

        The key finding cites `anchor`; the driver cites only `driver` and
        shares no fact key, so the evidence-sharing rule calls it off topic. It
        names the metric the question asks about, so it is not.
        """

        state = self._state()
        draft = ReportDraft(
            summary="本报告核验营收与毛利率的变化。",
            key_findings=[
                ReportClaim(text="蔚来2024年营业收入为657.3亿元。", evidence_ids=["anchor"])
            ],
            detailed_analysis=[
                ReportSection(
                    sub_question_id="rev_gm_values",
                    heading="驱动因素",
                    claims=[
                        ReportClaim(
                            text="2023年6月蔚来全系降价3万元，带动交付量回升，对全年营收形成支撑。",
                            evidence_ids=["driver"],
                        ),
                        ReportClaim(
                            text="匈牙利工厂仍处于建设阶段。",
                            evidence_ids=["offtopic"],
                        ),
                    ],
                )
            ],
        )

        reporter = ReporterAgent()
        report, _, _ = reporter._render_llm_report(state, draft)
        flow = reporter.last_stats["analysis_flow"]
        body = report.split("## 参考来源", 1)[0]

        self.assertIn(
            "## 详细分析",
            body,
            "the reader received no analysis section at all: "
            f"{reporter.last_stats['dropped_analysis_claims']}",
        )
        analysis = body.split("## 详细分析", 1)[1].split("\n## ", 1)[0]

        self.assertEqual(flow["rendered_lines"], 1)
        self.assertEqual(flow["claims_dropped_unrelated"], 1)
        self.assertIn("全系降价3万元", analysis)
        self.assertNotIn("匈牙利工厂", analysis)


class FootnoteResolutionTests(unittest.TestCase):
    """R100: one footnote can stand for several Evidence items."""

    def test_a_line_is_checked_against_every_evidence_behind_its_footnote(self) -> None:
        """The last blocker between R100's fixes and the reader.

        `build_footnote_maps` gives one number to every Evidence sharing a
        source, so two extracts from one article share `[^1]`. The downgrade
        resolved that number through a dict comprehension and kept whichever
        came last, then checked a margin line against a revenue extract and
        deleted it as unverifiable -- while it was quoting its own source.
        """

        state = ResearchState(topic="蔚来 2024 年营收和毛利率")
        state.plan = ResearchPlan(
            topic=state.topic,
            sub_questions=[
                SubQuestion(
                    id="rev_gm",
                    question="蔚来 2024 年营收和毛利率如何变化？",
                    search_queries=["fixture"],
                    structured_data_requests=[
                        StructuredDataRequest(
                            capability="financial_indicators",
                            symbol="NIO",
                            metrics=["营业收入", "主营业务毛利率"],
                            periods=["20241231"],
                        )
                    ],
                )
            ],
        )
        shared_source = "https://example.com/one-article"
        state.evidence_store = [
            Evidence(
                id="margin",
                research_id=state.research_id,
                sub_question_id="rev_gm",
                claim="整车毛利率12.2%，同比提升6个百分点",
                claim_type="data",
                source_url=shared_source,
                source_title="One article",
                source_pub_date=date(2025, 3, 21),
                extract_text="整车毛利率12.2%，同比提升6个百分点",
            ),
            Evidence(
                id="revenue",
                research_id=state.research_id,
                sub_question_id="rev_gm",
                claim="蔚来2024年上半年营收为174.5亿元，同比增长98.9%",
                claim_type="data",
                source_url=shared_source,
                source_title="One article",
                source_pub_date=date(2025, 3, 21),
                extract_text="蔚来2024年上半年营收为174.5亿元，同比增长98.9%",
            ),
        ]
        draft = ReportDraft(
            summary="本报告核验营收与毛利率。",
            detailed_analysis=[
                ReportSection(
                    sub_question_id="rev_gm",
                    heading="驱动因素",
                    claims=[
                        ReportClaim(
                            text="2024年上半年整车毛利率为12.2%，同比提升6个百分点，改善幅度显著。",
                            evidence_ids=["margin"],
                        ),
                        ReportClaim(
                            text="2024年上半年营收174.5亿元，同比增长98.9%，增速高于全年。",
                            evidence_ids=["revenue"],
                        ),
                    ],
                )
            ],
        )

        pack = load_domain_pack("finance")
        reporter = ReporterAgent(
            grounded_fact_renderer=pack.grounded_fact_renderer(),
            numeric_citation_policy=pack.numeric_citation_policy(),
            domain_pack=pack,
        )
        rendered, _, _ = reporter._render_llm_report(state, draft)
        reporter.last_stats["fallback"] = False
        report = reporter._enforce_reader_fidelity(
            rendered,
            state,
            build_footnote_maps(state.evidence_store).evidence_id_to_footnote,
        )
        analysis = report.split("## 详细分析", 1)[1].split("\n## ", 1)[0]

        self.assertNotIn(
            "未通过 Evidence 保真守卫",
            analysis,
            "a line quoting its own source was deleted as unverifiable",
        )
        self.assertIn("12.2%", analysis)
        self.assertIn("174.5亿元", analysis)
