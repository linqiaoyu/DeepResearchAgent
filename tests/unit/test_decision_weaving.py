from __future__ import annotations

import unittest
from datetime import date

from pydantic import ValidationError

from deepresearch_agent.orchestration import (
    BoundedLoop,
    BranchBudget,
    DecisionContext,
    LoopIterationResult,
    LoopSpec,
    SufficiencyThresholds,
    build_decision_context,
    evaluate_research_sufficiency,
    refine_research_plan,
)
from deepresearch_agent.schemas import (
    CriticReport,
    Issue,
    ResearchPlan,
    ResearchState,
    RetryTask,
    SubQuestion,
)
from deepresearch_agent.settings import Settings


def _planned_state() -> ResearchState:
    state = ResearchState(topic="决策编织")
    state.plan = ResearchPlan(
        topic=state.topic,
        sub_questions=[
            SubQuestion(
                id="verify",
                question="核实营收",
                search_queries=["旧查询"],
            ),
            SubQuestion(
                id="explore",
                question="寻找新市场",
                search_queries=["旧市场查询"],
            ),
        ],
    )
    return state


class DecisionContextTest(unittest.TestCase):
    def test_context_is_deeply_read_only_and_aggregates_all_inputs(self) -> None:
        state = _planned_state()
        task = RetryTask(
            reason="口径缺口",
            query="核实",
            sub_question_id="verify",
        )
        state.critic_report = CriticReport(
            passed=False,
            overall_quality=0.5,
            issues=[
                Issue(
                    issue_type="numeric_conflict",
                    severity="high",
                    message="营收数字冲突",
                    suggested_retry_task=task,
                )
            ],
            retry_tasks=[task],
        )
        state.metadata["prior_memory"] = {
            "classifications": [
                {"sub_question_id": "verify", "kind": "verify"}
            ]
        }
        context = build_decision_context(
            state,
            iteration=2,
            budget_total=10,
            budget_used=7,
            budget_snapshot={
                "verify": {
                    "allocated": 5,
                    "used": 4,
                    "remaining": 1,
                }
            },
        )

        self.assertEqual(context.iteration, 2)
        self.assertEqual(context.budget.remaining, 3)
        self.assertEqual(context.budget.branches[0].remaining, 1)
        self.assertEqual(context.prior_classifications[0].kind, "verify")
        self.assertEqual(
            context.unresolved_critic_issues[0].sub_question_ids,
            ("verify",),
        )
        with self.assertRaises(ValidationError):
            context.iteration = 3
        self.assertIsInstance(context.unresolved_critic_issues, tuple)

    def test_default_switch_is_off(self) -> None:
        settings = Settings(storage_path="test.db")
        self.assertFalse(settings.decision_weaving_enabled)


class WovenDecisionDependencyTest(unittest.TestCase):
    def test_low_context_budget_tightens_loop_stop(self) -> None:
        state = _planned_state()
        context = DecisionContext.model_validate(
            {
                "iteration": 1,
                "budget": {"total": 10, "used": 9, "remaining": 1},
            }
        )
        loop = BoundedLoop(
            LoopSpec(
                max_iterations=4,
                budget_ceiling=20,
                no_progress_window=4,
                progress_metric=lambda _state: 0.5,
                on_exhausted=lambda _state, _boundary: None,
            ),
            step=lambda _state, _context: LoopIterationResult(
                budget_consumed=0
            ),
        )

        outcome = loop.advance(
            state,
            loop.start(state),
            LoopIterationResult(budget_consumed=1),
            decision_context=context,
            budget_remaining_ratio_threshold=0.2,
        )

        self.assertEqual(outcome.route, "stop")
        self.assertEqual(
            outcome.stop_boundary,
            "decision_context_budget_threshold",
        )
        decision = state.agent_decisions[-1]
        self.assertIn("因预算约束提前收敛", decision.outcome)
        self.assertEqual(
            decision.inputs["decision_context_fields"],
            ["iteration", "budget", "sufficiency"],
        )

    def test_verify_classification_receives_budget_floor(self) -> None:
        state = _planned_state()
        state.metadata["prior_memory"] = {
            "classifications": [
                {"sub_question_id": "verify", "kind": "verify"},
                {"sub_question_id": "explore", "kind": "explore"},
            ]
        }
        budget = BranchBudget(total_budget=3, per_branch_cap=3)
        budget.allocate(["verify", "explore"], state)
        budget.consume("verify", 1, state)
        budget.consume("explore", 1, state)
        context = build_decision_context(
            state,
            iteration=1,
            budget_total=3,
            budget_used=2,
            budget_snapshot=budget.snapshot(),
        )

        allocations = budget.reallocate(
            {"verify": 0.9, "explore": 0.1},
            state,
            decision_context=context,
            verify_min_allocation=2,
        )

        self.assertEqual(allocations, {"explore": 1, "verify": 2})
        decision = state.agent_decisions[-1]
        self.assertIn("verify_floor", decision.outcome)
        self.assertIn(
            "prior_classifications",
            decision.inputs["decision_context_fields"],
        )

    def test_unresolved_issue_targets_next_replan(self) -> None:
        state = _planned_state()
        task = RetryTask(
            reason="营收数值矛盾",
            query="核实营收数值",
            sub_question_id="verify",
        )
        state.critic_report = CriticReport(
            passed=False,
            overall_quality=0.4,
            issues=[
                Issue(
                    issue_type="numeric_conflict",
                    severity="high",
                    message="营收增长率与绝对值不一致",
                    suggested_retry_task=task,
                )
            ],
            retry_tasks=[task],
        )
        sufficiency = evaluate_research_sufficiency(
            state,
            as_of=date(2026, 7, 24),
            thresholds=SufficiencyThresholds(),
        )
        context = build_decision_context(
            state,
            iteration=2,
            sufficiency=sufficiency,
        )

        refined = refine_research_plan(
            state,
            sufficiency,
            as_of=date(2026, 7, 24),
            iteration=2,
            decision_context=context,
        )

        self.assertIn(
            "resolve numeric_conflict",
            refined["verify"][0],
        )
        decision = state.agent_decisions[-1]
        self.assertIn(
            "unresolved_critic_issues",
            decision.inputs["decision_context_fields"],
        )
        self.assertEqual(
            decision.inputs["decision_context"][
                "unresolved_critic_issues"
            ][0]["message"],
            "营收增长率与绝对值不一致",
        )


if __name__ == "__main__":
    unittest.main()
