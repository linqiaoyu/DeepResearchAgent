from __future__ import annotations

import unittest

from deepresearch_agent.agents import PlannerAgent
from deepresearch_agent.schemas import ResearchRequest


class SchemaTests(unittest.TestCase):
    def test_research_request_defaults(self) -> None:
        request = ResearchRequest(topic="AI Agent 在财富管理行业的落地机会研究")
        self.assertEqual(request.depth_level, 2)
        self.assertEqual(request.output_format, "markdown")

    def test_planner_outputs_subquestions(self) -> None:
        plan = PlannerAgent().plan("AI Agent 在财富管理行业的落地机会研究", depth_level=2)
        self.assertGreaterEqual(len(plan.sub_questions), 4)
        self.assertTrue(plan.success_criteria)
        self.assertIn("market_pain", {item.id for item in plan.sub_questions})


if __name__ == "__main__":
    unittest.main()

