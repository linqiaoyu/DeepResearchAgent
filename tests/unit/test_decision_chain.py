from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

from deepresearch_agent.decisions import append_decision_chain
from deepresearch_agent.schemas import AgentDecision
from deepresearch_agent.settings import Settings
from deepresearch_agent.workflow import DeepResearchEngine


class DecisionChainRenderingTest(unittest.TestCase):
    def test_renders_dependencies_as_tradeoffs_not_flat_events(self) -> None:
        common_context = {
            "budget": {
                "total": 10,
                "used": 9,
                "remaining": 1,
                "branches": [],
            },
            "sufficiency": [
                {
                    "sub_question_id": "players",
                    "score": 0.5,
                    "sufficient": False,
                    "gaps": ["unresolved_critic_issues"],
                }
            ],
            "prior_classifications": [
                {"sub_question_id": "revenue", "kind": "verify"}
            ],
            "unresolved_critic_issues": [
                {
                    "issue_type": "numeric_inconsistency",
                    "message": "同比不一致",
                }
            ],
        }
        decisions = [
            AgentDecision(
                decision_type="branch_budget_reallocate",
                made_by="BranchBudget",
                inputs={
                    "decision_context_fields": [
                        "budget",
                        "sufficiency",
                        "prior_classifications",
                    ],
                    "decision_context": common_context,
                },
                criterion="verify floor",
                outcome="reallocated_with_verify_floor={'revenue': 2}",
            ),
            AgentDecision(
                decision_type="bounded_loop_control",
                made_by="BoundedLoop",
                inputs={
                    "decision_context_fields": ["budget", "sufficiency"],
                    "decision_context": common_context,
                },
                criterion="budget and sufficiency",
                outcome="stop_budget_constrained:因预算约束提前收敛",
            ),
            AgentDecision(
                decision_type="research_replan",
                made_by="PlannerAgent",
                inputs={
                    "decision_context_fields": [
                        "unresolved_critic_issues"
                    ],
                    "decision_context": common_context,
                },
                criterion="critic feedback",
                outcome="refined_queries={'players': ['核实同比']}",
            ),
        ]

        report = append_decision_chain("正文", decisions)

        self.assertIn("## 决策链", report)
        self.assertIn("余额 1/10", report)
        self.assertIn("verify 子问题 ['revenue']", report)
        self.assertIn("仍有缺口的子问题 ['players']", report)
        self.assertIn("numeric_inconsistency", report)
        self.assertIn("同一只读上下文", report)

    def test_no_woven_decisions_preserves_report_byte_for_byte(self) -> None:
        self.assertEqual(
            append_decision_chain("原始报告\n", []),
            "原始报告\n",
        )

    def test_enabled_engine_report_contains_decision_chain(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = Settings(
                storage_path=Path(temp_dir) / "research.db",
                runs_root=Path(temp_dir) / "runs",
                structured_logging_enabled=False,
                run_manifest_enabled=False,
                max_critic_iter=1,
                research_loop_enabled=True,
                research_loop_max_iterations=2,
                research_loop_no_progress_window=5,
                decision_weaving_enabled=True,
            )
            engine = DeepResearchEngine(settings=settings)
            state = engine.run(
                topic="AI Agent 在财富管理行业的落地机会研究",
                depth_level=1,
            )
            engine._checkpoint_conn.close()

        self.assertNotIn("## 决策链", state.final_report or "")
        self.assertTrue(state.agent_decisions)


if __name__ == "__main__":
    unittest.main()
