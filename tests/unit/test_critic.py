from __future__ import annotations

import unittest
from datetime import date

from deepresearch_agent.agents import CriticAgent, PlannerAgent
from deepresearch_agent.schemas import Evidence, ResearchState


class CriticTests(unittest.TestCase):
    def test_detects_numeric_conflict_and_outdated_source(self) -> None:
        plan = PlannerAgent().plan("AI Agent 在财富管理行业的落地机会研究", depth_level=1)
        state = ResearchState(topic=plan.topic, plan=plan)
        state.evidence_store = [
            Evidence(
                research_id=state.research_id,
                sub_question_id="market_pain",
                claim="Advisor productivity improved 18% in the first pilot.",
                claim_type="data",
                source_url="https://a.example",
                source_title="A",
                source_pub_date=date(2026, 4, 1),
                extract_text="Advisor productivity improved 18% in the first pilot.",
            ),
            Evidence(
                research_id=state.research_id,
                sub_question_id="current_adoption",
                claim="Advisor productivity improved 31% after workflow embedding.",
                claim_type="data",
                source_url="https://b.example",
                source_title="B",
                source_pub_date=date(2024, 1, 1),
                extract_text="Advisor productivity improved 31% after workflow embedding.",
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


if __name__ == "__main__":
    unittest.main()

