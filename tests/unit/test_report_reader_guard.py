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
