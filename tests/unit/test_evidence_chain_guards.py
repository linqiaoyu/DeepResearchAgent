from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path

from deepresearch_agent.agents import ReporterAgent
from deepresearch_agent.domains.registry import load_domain_pack
from deepresearch_agent.orchestration.research_loop import (
    MAX_REPLAN_QUERY_CHINESE_CHARS,
    MAX_TITLE_COMMON_SUBSTRING_CHARS,
    SufficiencyThresholds,
    build_replan_query,
    evaluate_research_sufficiency,
    longest_common_substring_length,
)
from deepresearch_agent.schemas import (
    CriticReport,
    Evidence,
    NumericFields,
    ResearchPlan,
    ResearchState,
    StructuredDataRequest,
    SubQuestion,
)
from deepresearch_agent.tools.tavily_search import TavilySearchProvider


ROOT = Path(__file__).resolve().parents[2]


class EvidenceChainGuardTests(unittest.TestCase):
    def test_f1_structured_queries_pass_all_three_guards(self) -> None:
        # Six 019-B subjects x three document types: no network is involved.
        cases = [
            ("贵州茅台2024年业绩及产品收入结构", "贵州茅台", "600519", "营业总收入", "20241231"),
            ("宁德时代2024年业绩与盈利能力变化", "宁德时代", "300750", "营业收入", "20241231"),
            ("宁德时代与比亚迪2024年动力电池市场份额", "宁德时代", "300750", "动力电池装机量", "20241231"),
            ("中国创新药License-out交易金额与首付款", "恒瑞医药", "600276", "首付款", "20241231"),
            ("宁德时代匈牙利工厂建设与投产进展", "宁德时代", "300750", "匈牙利工厂", "20220812"),
            ("中国光伏行业自律减产与价格治理", "中国光伏行业协会", "CPIA", "行业自律", "20241231"),
        ]
        document_types = ("公告", "年度报告", "统计发布")
        generated: list[tuple[str, str]] = []
        for index, (title, company, symbol, metric, period) in enumerate(cases):
            sub_question = SubQuestion(
                id=f"q{index}", question=title, search_queries=[],
                structured_data_requests=[StructuredDataRequest(
                    capability="financial_indicators", company_name=company,
                    symbol=symbol, metrics=[metric], periods=[period],
                )],
            )
            for document_type in document_types:
                query = build_replan_query(sub_question, document_type)
                generated.append((title, query))
                self.assertLessEqual(
                    len("".join(char for char in query if "\u4e00" <= char <= "\u9fff")),
                    MAX_REPLAN_QUERY_CHINESE_CHARS,
                )
                self.assertLessEqual(
                    longest_common_substring_length(query, title),
                    MAX_TITLE_COMMON_SUBSTRING_CHARS,
                )
                self.assertTrue(
                    any(token in query for token in load_domain_pack("finance").document_type_tokens())
                )
                self.assertIn(symbol, query)
                self.assertNotIn(title, query)
        self.assertEqual(len(generated), 18)

    def test_f2_summary_fails_closed_without_critic_and_shows_score_with_critic(self) -> None:
        state = self._state([self._evidence("key")])
        report = ReporterAgent().report(state)
        self.assertIn("Critic 未执行", report)
        self.assertNotRegex(report, r"Critic 质量分为\s*\d")
        state.critic_report = CriticReport(passed=True, overall_quality=0.85)
        report = ReporterAgent().report(state)
        self.assertIn("Critic 质量分为 0.85", report)

    def test_f3_pdf_date_and_unknown_freshness_are_fail_closed(self) -> None:
        provider = TavilySearchProvider("test-key")
        source = provider._pdf_source(
            "https://issuer.example/catl-2022-070.pdf",
            (ROOT / "tests/fixtures/catl_2022_070_excerpt.pdf").read_bytes(),
        )
        self.assertEqual(source.published_at, date(2022, 8, 12))
        unknown = provider._publication_date_from_html("<html>no date</html>", "https://example.com/no-date")
        self.assertIsNone(unknown)
        state = self._state([self._evidence("unknown-date", published=None)])
        metrics = evaluate_research_sufficiency(
            state, as_of=date(2026, 7, 25), thresholds=SufficiencyThresholds()
        ).by_sub_question[0]
        self.assertIsNone(metrics.freshest_evidence_age_days)
        self.assertNotIn("freshness", metrics.gaps)
        report = ReporterAgent().report(state)
        self.assertIn("(unknown)", report)
        self.assertNotIn("1970-01-01", report)

    def test_f4_default_renderer_removes_repeated_detail_and_routes_unlinked_fact(self) -> None:
        key = self._evidence("key", metric="营业收入")
        key_rows = [key, *[self._evidence(f"key-{index}", metric="营业收入") for index in range(1, 6)]]
        unrelated = self._evidence("unrelated", metric="匈牙利工厂")
        state = self._state([*key_rows, unrelated])
        report = ReporterAgent().report(state)
        supplemental = report.split("## 补充事实", 1)[1].split("## 风险与限制", 1)[0]
        self.assertNotIn("## 详细分析", report)
        self.assertIn(unrelated.claim, supplemental)

    def _state(self, evidence: list[Evidence]) -> ResearchState:
        state = ResearchState(topic="宁德时代证据链测试")
        state.plan = ResearchPlan(topic=state.topic, sub_questions=[SubQuestion(
            id="sq", question="宁德时代业绩和匈牙利工厂进展", search_queries=[]
        )])
        state.evidence_store = evidence
        return state

    def _evidence(self, evidence_id: str, *, metric: str = "营业收入", published: date | None = date(2025, 3, 15)) -> Evidence:
        return Evidence(
            id=evidence_id, research_id="run", sub_question_id="sq",
            claim=f"宁德时代{metric}已披露。", claim_type="data",
            source_url=f"https://example.com/{evidence_id}", source_title=evidence_id,
            source_pub_date=published, extract_text="fixture", numeric_fields=NumericFields(
                entity="宁德时代", metric_name=metric, period="20241231", value=1, unit="亿元"
            ),
        )


if __name__ == "__main__":
    unittest.main()
