from __future__ import annotations

import unittest
from datetime import date

from deepresearch_agent.agents import ReporterAgent
from deepresearch_agent.schemas import Evidence, NumericFields, ResearchPlan, ResearchState, SubQuestion


class ReporterFinanceTemplateTests(unittest.TestCase):
    def test_report_includes_disclaimer_as_of_and_numeric_context(self) -> None:
        state = ResearchState(topic="宁德时代业绩研究")
        state.plan = ResearchPlan(
            topic=state.topic,
            sub_questions=[
                SubQuestion(id="finance", question="宁德时代 2024 年业绩如何？", search_queries=["宁德时代 业绩"])
            ],
        )
        state.evidence_store = [
            Evidence(
                id="e1",
                research_id=state.research_id,
                sub_question_id="finance",
                claim="宁德时代 2024 年累计归母净利润为 507.45 亿元。",
                claim_type="data",
                source_url="https://example.com/catl",
                source_title="CATL",
                source_pub_date=date(2026, 4, 20),
                extract_text="宁德时代 2024 年累计归母净利润为 507.45 亿元。",
                numeric_fields=NumericFields(
                    entity="宁德时代",
                    metric_name="归母净利润",
                    period="20241231",
                    dimension="累计",
                    value=50_745_000_000,
                    unit="元",
                ),
            )
        ]

        report = ReporterAgent().report(state)

        self.assertIn("免责声明：本报告为研究性输出，不构成投资建议。", report)
        self.assertIn("数据截至：2026-04-20", report)
        self.assertIn("报告期/时点: 20241231", report)
        self.assertIn("口径: 累计", report)
        self.assertIn("单位: 元", report)


if __name__ == "__main__":
    unittest.main()
