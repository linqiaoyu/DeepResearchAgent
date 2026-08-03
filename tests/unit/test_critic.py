from __future__ import annotations

import unittest
from datetime import date

from deepresearch_agent.agents import CriticAgent, PlannerAgent
from deepresearch_agent.schemas import (
    Evidence,
    NumericFields,
    ResearchPlan,
    ResearchState,
    RetryTask,
    StructuredDataRequest,
    SubQuestion,
)


class CriticTests(unittest.TestCase):
    def _exact_financial_state(self) -> ResearchState:
        state = ResearchState(
            topic="贵州茅台 2025 年营业收入及同比"
        )
        state.plan = ResearchPlan(
            topic=state.topic,
            sub_questions=[
                SubQuestion(
                    id="finance",
                    question=state.topic,
                    search_queries=["600519 年度报告"],
                    structured_data_requests=[
                        StructuredDataRequest(
                            capability="financial_indicators",
                            company_name="贵州茅台",
                            symbol="600519",
                            periods=["20251231", "20241231"],
                            metrics=["营业收入"],
                        )
                    ],
                )
            ],
            success_criteria=["retrieve the requested figures"],
        )
        state.evidence_store = [
            Evidence(
                research_id=state.research_id,
                sub_question_id="finance",
                claim="2025年营业收入为1688.38亿元。",
                claim_type="data",
                source_url="https://cninfo.test/annual.pdf",
                source_title="贵州茅台2025年年度报告",
                source_pub_date=date(2026, 4, 16),
                extract_text=(
                    "营业收入 168,838,102,514.79 "
                    "170,899,152,276.34 -1.21"
                ),
                numeric_fields=NumericFields(
                    entity="贵州茅台",
                    metric_name="营业收入",
                    period="20251231",
                    dimension="年度主要会计数据",
                    value=168_838_102_514.79,
                    unit="元",
                ),
                source_tier="primary",
            )
        ]
        return state

    def test_exact_financial_lookup_does_not_require_counterargument(
        self,
    ) -> None:
        report = CriticAgent(
            today=date(2026, 7, 26)
        ).critique(
            self._exact_financial_state()
        )

        self.assertTrue(report.passed)
        self.assertNotIn(
            "missing_counterargument",
            {issue.issue_type for issue in report.issues},
        )
        self.assertEqual(report.retry_tasks, [])

    def test_explicit_risk_financial_lookup_still_requires_counterargument(
        self,
    ) -> None:
        state = self._exact_financial_state()
        assert state.plan is not None
        state.plan.success_criteria.append(
            "identify material risk and compliance constraints"
        )

        report = CriticAgent(
            today=date(2026, 7, 26)
        ).critique(state)

        self.assertIn(
            "missing_counterargument",
            {issue.issue_type for issue in report.issues},
        )

    def test_mixed_financial_and_narrative_plan_requires_counterargument(
        self,
    ) -> None:
        state = self._exact_financial_state()
        assert state.plan is not None
        state.plan.sub_questions.append(
            SubQuestion(
                id="strategy",
                question="公司的渠道策略如何变化",
                search_queries=["贵州茅台 渠道策略"],
            )
        )
        state.evidence_store.append(
            Evidence(
                research_id=state.research_id,
                sub_question_id="strategy",
                claim="公司调整了渠道结构。",
                claim_type="fact",
                source_url="https://cninfo.test/strategy",
                source_title="渠道公告",
                source_pub_date=date(2026, 4, 16),
                extract_text="公司调整了渠道结构。",
            )
        )

        report = CriticAgent(
            today=date(2026, 7, 26)
        ).critique(state)

        self.assertIn(
            "missing_counterargument",
            {issue.issue_type for issue in report.issues},
        )
    def _data_evidence(
        self,
        state: ResearchState,
        evidence_id: str,
        claim: str,
        source_url: str,
        value: float,
        metric_name: str = "归母净利润",
        period: str = "20241231",
        dimension: str = "累计",
        source_kind: str = "text",
    ) -> Evidence:
        return Evidence(
            id=evidence_id,
            research_id=state.research_id,
            sub_question_id="market_pain",
            claim=claim,
            claim_type="data",
            source_kind=source_kind,
            source_url=source_url,
            source_title=evidence_id,
            source_pub_date=date(2026, 4, 1),
            extract_text=claim,
            numeric_fields=NumericFields(
                entity="宁德时代",
                metric_name=metric_name,
                period=period,
                dimension=dimension,
                value=value,
                unit="元",
            ),
        )

    def test_detects_numeric_conflict_and_outdated_source(self) -> None:
        plan = PlannerAgent().plan("AI Agent 在财富管理行业的落地机会研究", depth_level=1)
        state = ResearchState(topic=plan.topic, plan=plan)
        state.evidence_store = [
            self._data_evidence(
                state,
                "a",
                "宁德时代 2024 年累计归母净利润为 507.45 亿元。",
                "https://a.example",
                50_745_000_000,
            ),
            self._data_evidence(
                state,
                "b",
                "宁德时代 2024 年累计归母净利润为 410.00 亿元。",
                "https://b.example",
                41_000_000_000,
            ),
            Evidence(
                research_id=state.research_id,
                sub_question_id="current_adoption",
                claim="宁德时代 2024 年累计归母净利润使用旧来源。",
                claim_type="data",
                source_url="https://old.example",
                source_title="Old",
                source_pub_date=date(2024, 1, 1),
                extract_text="宁德时代 2024 年累计归母净利润使用旧来源。",
            ),
            Evidence(
                research_id=state.research_id,
                sub_question_id="risk_governance",
                claim="Regulatory risk requires human approval.",
                claim_type="opinion",
                source_url="https://c.example",
                source_title="C",
                source_pub_date=date(2026, 1, 1),
                extract_text="Regulatory risk requires human approval.",
            ),
        ]
        report = CriticAgent().critique(state)
        issue_types = {issue.issue_type for issue in report.issues}
        self.assertIn("numeric_conflict", issue_types)
        self.assertIn("outdated_source", issue_types)
        self.assertTrue(report.retry_tasks)
        self.assertTrue(all(task.sub_question_id for task in report.retry_tasks))
        self.assertIn("market_pain", {task.sub_question_id for task in report.retry_tasks})
        self.assertIn("current_adoption", {task.sub_question_id for task in report.retry_tasks})

    def test_finance_false_conflicts_do_not_trigger_without_four_key_match(self) -> None:
        state = ResearchState(topic="宁德时代业绩研究")
        state.evidence_store = [
            self._data_evidence(
                state,
                "attributable",
                "宁德时代 2024 年累计归母净利润为 507.45 亿元。",
                "https://a.example",
                50_745_000_000,
                metric_name="归母净利润",
            ),
            self._data_evidence(
                state,
                "net",
                "宁德时代 2024 年累计净利润为 520.00 亿元。",
                "https://b.example",
                52_000_000_000,
                metric_name="净利润",
            ),
            self._data_evidence(
                state,
                "quarter",
                "宁德时代 2024 年单季归母净利润为 105.10 亿元。",
                "https://c.example",
                10_510_000_000,
                dimension="单季",
            ),
        ]

        report = CriticAgent().critique(state)

        self.assertNotIn("numeric_conflict", {issue.issue_type for issue in report.issues})

    def test_structured_official_mismatch_is_high_numeric_conflict(self) -> None:
        state = ResearchState(topic="宁德时代业绩研究")
        state.evidence_store = [
            self._data_evidence(
                state,
                "text",
                "宁德时代 2024 年累计归母净利润为 410.00 亿元。",
                "https://text.example",
                41_000_000_000,
            ),
            self._data_evidence(
                state,
                "structured",
                "宁德时代 2024 年累计归母净利润为 507.45 亿元。",
                "akshare://financial_indicators/300750/20241231/归母净利润",
                50_745_000_000,
                source_kind="structured",
            ),
        ]

        report = CriticAgent().critique(state)
        conflicts = [issue for issue in report.issues if issue.issue_type == "numeric_conflict"]

        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].severity, "high")
        self.assertIn("structured official data source", conflicts[0].message)

    def test_temporal_conflict_detects_same_event_with_different_dates(self) -> None:
        state = ResearchState(topic="宁德时代扩产研究")
        state.evidence_store = [
            Evidence(
                id="date-a",
                research_id=state.research_id,
                sub_question_id="expansion",
                claim="宁德时代欧洲工厂投产日期为2025年6月。",
                claim_type="fact",
                source_url="https://a.example",
                source_title="A",
                source_pub_date=date(2026, 1, 1),
                extract_text="宁德时代欧洲工厂投产日期为2025年6月。",
            ),
            Evidence(
                id="date-b",
                research_id=state.research_id,
                sub_question_id="expansion",
                claim="宁德时代欧洲工厂投产日期为2025年9月。",
                claim_type="fact",
                source_url="https://b.example",
                source_title="B",
                source_pub_date=date(2026, 1, 1),
                extract_text="宁德时代欧洲工厂投产日期为2025年9月。",
            ),
        ]

        report = CriticAgent().critique(state)

        self.assertIn("temporal_conflict", {issue.issue_type for issue in report.issues})

    def test_as_of_controls_outdated_source_boundary(self) -> None:
        state = ResearchState(topic="as of test")
        state.evidence_store = [
            Evidence(
                id="timed",
                research_id=state.research_id,
                sub_question_id="finance",
                claim="A time-sensitive data claim.",
                claim_type="data",
                source_url="https://example.com/timed",
                source_title="Timed",
                source_pub_date=date(2025, 6, 1),
                extract_text="A time-sensitive data claim.",
            )
        ]

        at_boundary = CriticAgent(today=date(2026, 6, 1)).critique(state)
        past_boundary = CriticAgent(today=date(2026, 6, 2)).critique(state)

        self.assertNotIn("outdated_source", {issue.issue_type for issue in at_boundary.issues})
        self.assertIn("outdated_source", {issue.issue_type for issue in past_boundary.issues})

    def test_historical_annual_filing_is_not_a_stale_news_source(self) -> None:
        state = ResearchState(topic="NIO 2024 annual report")
        state.evidence_store = [
            Evidence(
                id="annual-filing",
                research_id=state.research_id,
                sub_question_id="finance",
                claim="NIO reported 2024 revenue.",
                claim_type="data",
                source_url="https://www.sec.gov/Archives/edgar/data/1736541/nio-20241231x20f.htm",
                source_title="NIO Inc. 2024 Annual Report on Form 20-F",
                source_pub_date=date(2025, 4, 8),
                extract_text="NIO reported 2024 revenue.",
            )
        ]

        report = CriticAgent(today=date(2026, 8, 2)).critique(state)

        self.assertNotIn("outdated_source", {issue.issue_type for issue in report.issues})

    def test_company_facts_annual_data_is_not_a_stale_news_source(self) -> None:
        state = ResearchState(topic="NIO 2024 results")
        state.evidence_store = [
            Evidence(
                id="company-facts",
                research_id=state.research_id,
                sub_question_id="finance",
                claim="NIO reported 2024 gross profit.",
                claim_type="data",
                source_url="https://www.sec.gov/Archives/edgar/data/1736541/000141057825000661/",
                source_title="SEC EDGAR Company Facts CIK0001736541 毛利",
                source_pub_date=date(2025, 4, 8),
                extract_text="NIO reported 2024 gross profit.",
            )
        ]

        report = CriticAgent(today=date(2026, 8, 2)).critique(state)

        self.assertNotIn("outdated_source", {issue.issue_type for issue in report.issues})

    def test_annual_filing_legal_template_is_not_an_unverified_projection(self) -> None:
        state = ResearchState(topic="NIO 2024 annual report")
        state.evidence_store = [
            Evidence(
                id="legal-template",
                research_id=state.research_id,
                sub_question_id="finance",
                claim=(
                    "You should read this annual report completely with the understanding "
                    "that our actual future results may be materially different from what we expect."
                ),
                claim_type="projection",
                source_url="https://www.sec.gov/Archives/edgar/data/1736541/nio-20241231x20f.htm",
                source_title="NIO Inc. 2024 Annual Report on Form 20-F",
                source_pub_date=date(2025, 4, 8),
                extract_text="forward-looking statement disclaimer",
                confidence=0.1,
            )
        ]

        report = CriticAgent(today=date(2026, 8, 2)).critique(state)

        self.assertNotIn("unverified_projection", {issue.issue_type for issue in report.issues})

    def test_outdated_source_retry_uses_structured_verification_query(self) -> None:
        state = ResearchState(topic="retry query test")
        state.evidence_store = [
            self._data_evidence(
                state,
                "old-data",
                "宁德时代 2024 年累计归母净利润为 507.45 亿元，这是一条很长的原始 claim，不应直接作为检索查询。",
                "https://old.example",
                50_745_000_000,
            ).model_copy(update={"source_pub_date": date(2024, 1, 1)})
        ]

        report = CriticAgent(today=date(2026, 7, 8)).critique(state)
        outdated_tasks = [
            issue.suggested_retry_task
            for issue in report.issues
            if issue.issue_type == "outdated_source" and issue.suggested_retry_task
        ]

        self.assertEqual(len(outdated_tasks), 1)
        self.assertEqual(outdated_tasks[0].query, "宁德时代 归母净利润 20241231")
        self.assertNotIn("latest", outdated_tasks[0].query)
        self.assertNotIn("2026", outdated_tasks[0].query)
        self.assertLessEqual(len(outdated_tasks[0].query.split()), 10)

    def test_retry_task_sub_question_id_is_optional_for_old_checkpoints(self) -> None:
        task = RetryTask(reason="legacy retry", query="legacy query")

        self.assertIsNone(task.sub_question_id)


if __name__ == "__main__":
    unittest.main()
