from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from deepresearch_agent.orchestration import BranchBudget
from deepresearch_agent.schemas import ResearchState
from deepresearch_agent.settings import Settings
from deepresearch_agent.workflow import DeepResearchEngine


class BranchBudgetTest(unittest.TestCase):
    def test_initial_allocation_is_equal_and_respects_single_branch_cap(
        self,
    ) -> None:
        state = ResearchState(topic="budget")
        budget = BranchBudget(total_budget=10, per_branch_cap=4)

        allocations = budget.allocate(["a", "b", "c"], state)

        self.assertEqual(allocations, {"a": 4, "b": 3, "c": 3})
        self.assertLessEqual(max(allocations.values()), 4)
        decision = state.agent_decisions[-1]
        self.assertEqual(decision.decision_type, "branch_budget_allocate")
        self.assertEqual(
            decision.inputs["metrics"],
            {"a": None, "b": None, "c": None},
        )

    def test_reallocation_moves_remainder_toward_weaker_metric(self) -> None:
        state = ResearchState(topic="budget")
        budget = BranchBudget(total_budget=5, per_branch_cap=4)
        budget.allocate(["weak", "strong"], state)
        budget.consume("weak", 1, state)
        budget.consume("strong", 1, state)

        allocations = budget.reallocate(
            {"weak": 0.2, "strong": 0.9},
            state,
        )

        self.assertEqual(allocations, {"strong": 2, "weak": 3})
        decision = state.agent_decisions[-1]
        self.assertEqual(decision.decision_type, "branch_budget_reallocate")
        self.assertEqual(
            decision.inputs["metrics"],
            {"strong": 0.9, "weak": 0.2},
        )
        self.assertIn("lower measured coverage", decision.criterion)

    def test_branch_and_total_exhaustion_converge_with_visible_warnings(
        self,
    ) -> None:
        state = ResearchState(topic="budget")
        budget = BranchBudget(total_budget=2, per_branch_cap=2)
        budget.allocate(["a", "b"], state)

        self.assertTrue(budget.consume("a", 1, state))
        self.assertTrue(budget.snapshot()["a"]["exhausted"])
        self.assertIn("分支 a", "\n".join(state.metadata["coverage_warnings"]))

        self.assertTrue(budget.consume("b", 1, state))
        self.assertEqual(budget.total_remaining, 0)
        self.assertTrue(state.metadata["branch_budget"]["total_exhausted"])
        self.assertIn("全部分支收敛", "\n".join(state.metadata["coverage_warnings"]))

        completed = budget.snapshot()
        self.assertEqual(completed["a"]["used"], 1)
        self.assertEqual(completed["b"]["used"], 1)

    def test_consume_over_allocation_stops_without_discarding_prior_work(
        self,
    ) -> None:
        state = ResearchState(topic="budget")
        budget = BranchBudget(total_budget=1, per_branch_cap=1)
        budget.allocate(["a"], state)
        self.assertTrue(budget.consume("a", 1, state))

        self.assertFalse(budget.consume("a", 1, state))
        self.assertEqual(budget.snapshot()["a"]["used"], 1)
        self.assertTrue(budget.snapshot()["a"]["exhausted"])

    def test_enabled_engine_allocates_before_send_and_reallocates_after_join(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(
                storage_path=Path(tmp) / "research.db",
                runs_root=Path(tmp) / "runs",
                branch_budget_enabled=True,
                branch_total_budget=3,
                branch_single_cap=2,
                structured_logging_enabled=False,
                run_manifest_enabled=True,
                max_critic_iter=1,
                dynamic_capability_enabled=False,
            )
            engine = DeepResearchEngine(settings=settings)
            state = engine.run(topic="AI Agent 财富管理预算研究", depth_level=1)
            engine._checkpoint_conn.close()

        metadata = state.metadata["branch_budget"]
        self.assertEqual(metadata["phase"], "after_join")
        self.assertLessEqual(metadata["total_used"], 3)
        decision_types = [
            item.decision_type for item in state.agent_decisions
        ]
        self.assertEqual(decision_types[0], "branch_budget_allocate")
        self.assertIn("source_rerank", decision_types)
        self.assertIn("branch_budget_reallocate", decision_types)
        self.assertLess(
            decision_types.index("branch_budget_allocate"),
            decision_types.index("branch_budget_reallocate"),
        )
        self.assertIn("## Agent 决策记录", state.final_report or "")
        self.assertIn("branch_budget_allocate", state.final_report or "")


if __name__ == "__main__":
    unittest.main()
