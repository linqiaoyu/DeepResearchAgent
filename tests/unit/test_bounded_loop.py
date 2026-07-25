from __future__ import annotations

import unittest
from datetime import date

from deepresearch_agent.orchestration import (
    BoundedLoop,
    LoopIterationResult,
    LoopSpec,
)
from deepresearch_agent.schemas import Evidence, ResearchState
from deepresearch_agent.tools import RetryBudget
from deepresearch_agent.workflow.engine import _research_progress_metric


class BoundedLoopTest(unittest.TestCase):
    def _state(self) -> ResearchState:
        state = ResearchState(topic="bounded research")
        state.metadata["progress"] = 0.0
        state.metadata["completed_work"] = []
        return state

    def _spec(
        self,
        exhausted: list[str],
        *,
        max_iterations: int = 10,
        budget_ceiling: int = 10,
        no_progress_window: int = 10,
    ) -> LoopSpec:
        return LoopSpec(
            max_iterations=max_iterations,
            budget_ceiling=budget_ceiling,
            no_progress_window=no_progress_window,
            progress_metric=lambda state: float(state.metadata["progress"]),
            on_exhausted=lambda _state, boundary: exhausted.append(boundary),
        )

    def test_max_iterations_stops_native_back_edge_and_preserves_work(self) -> None:
        exhausted: list[str] = []
        state = self._state()

        def step(state: ResearchState, context) -> LoopIterationResult:
            state.metadata["progress"] += 1
            state.metadata["completed_work"].append(context.iteration)
            return LoopIterationResult(budget_consumed=1)

        result = BoundedLoop(
            self._spec(exhausted, max_iterations=2),
            step,
        ).run(state)

        self.assertEqual(result.metadata["completed_work"], [1, 2])
        self.assertEqual(exhausted, ["max_iterations"])
        self.assertEqual(len(result.agent_decisions), 2)
        self.assertEqual(
            result.agent_decisions[-1].outcome,
            "stop_exhausted:max_iterations",
        )

    def test_budget_ceiling_stops_and_marks_coverage_insufficient(self) -> None:
        exhausted: list[str] = []
        state = self._state()
        state.final_report = "已完成内容"

        def step(state: ResearchState, context) -> LoopIterationResult:
            state.metadata["progress"] += 1
            state.metadata["completed_work"].append(context.iteration)
            return LoopIterationResult(budget_consumed=1)

        result = BoundedLoop(
            self._spec(exhausted, budget_ceiling=2),
            step,
        ).run(state)

        self.assertEqual(result.metadata["completed_work"], [1, 2])
        self.assertIn("因 budget_ceiling 边界停止，覆盖可能不足", result.final_report or "")
        self.assertEqual(
            result.metadata["research_loop"]["stop_boundary"],
            "budget_ceiling",
        )

    def test_no_progress_window_stops_after_consecutive_flat_rounds(self) -> None:
        exhausted: list[str] = []
        state = self._state()

        def step(state: ResearchState, context) -> LoopIterationResult:
            state.metadata["completed_work"].append(context.iteration)
            return LoopIterationResult(budget_consumed=1)

        result = BoundedLoop(
            self._spec(exhausted, no_progress_window=2),
            step,
        ).run(state)

        self.assertEqual(result.metadata["completed_work"], [1, 2])
        self.assertEqual(exhausted, ["no_progress_window"])
        decision = result.agent_decisions[-1]
        self.assertEqual(decision.inputs["no_progress_count"], 2)
        self.assertEqual(
            decision.outcome,
            "stop_exhausted:no_progress_window",
        )

    def test_atomic_research_progress_prevents_early_no_progress_stop(self) -> None:
        state = ResearchState(topic="atomic progress")

        def step(state: ResearchState, context) -> LoopIterationResult:
            state.evidence_store.append(
                Evidence(
                    id=f"e-{context.iteration}",
                    research_id=state.research_id,
                    sub_question_id="q1",
                    claim=f"new evidence {context.iteration}",
                    claim_type="fact",
                    source_url=f"https://source-{context.iteration}.example/report",
                    source_title="source",
                    source_pub_date=date(2026, 7, 25),
                    extract_text=f"new evidence {context.iteration}",
                    source_tier="primary",
                )
            )
            return LoopIterationResult(budget_consumed=1)

        result = BoundedLoop(
            LoopSpec(
                max_iterations=4,
                budget_ceiling=10,
                no_progress_window=2,
                progress_metric=_research_progress_metric,
                on_exhausted=lambda _state, _boundary: None,
            ),
            step,
        ).run(state)

        self.assertEqual(len(result.evidence_store), 4)
        self.assertEqual(
            result.metadata["research_loop"]["stop_boundary"],
            "max_iterations",
        )
        self.assertEqual(result.agent_decisions[-1].inputs["no_progress_count"], 0)
        self.assertEqual(
            result.agent_decisions[-1].inputs["progress_components"],
            {
                "unique_evidence": 4,
                "independent_domains": 4,
                "primary_sources": 4,
                "unresolved_issues": 0,
            },
        )

    def test_atomic_research_progress_still_stops_true_stagnation(self) -> None:
        state = ResearchState(topic="atomic stagnation")
        result = BoundedLoop(
            LoopSpec(
                max_iterations=4,
                budget_ceiling=10,
                no_progress_window=2,
                progress_metric=_research_progress_metric,
                on_exhausted=lambda _state, _boundary: None,
            ),
            lambda _state, _context: LoopIterationResult(budget_consumed=1),
        ).run(state)
        self.assertEqual(
            result.metadata["research_loop"]["stop_boundary"],
            "no_progress_window",
        )
        self.assertEqual(len(result.agent_decisions), 2)

    def test_each_round_records_metric_criterion_outcome_and_alternatives(self) -> None:
        exhausted: list[str] = []
        state = self._state()

        def step(state: ResearchState, context) -> LoopIterationResult:
            state.metadata["progress"] += 0.5
            return LoopIterationResult(
                budget_consumed=1,
                stop_requested=context.iteration == 2,
                stop_reason="sufficient",
            )

        result = BoundedLoop(self._spec(exhausted), step).run(state)

        self.assertEqual(exhausted, [])
        self.assertEqual(len(result.agent_decisions), 2)
        for index, decision in enumerate(result.agent_decisions, start=1):
            self.assertEqual(decision.iteration, index)
            self.assertIn("metric_before", decision.inputs)
            self.assertIn("metric_after", decision.inputs)
            self.assertIn("stop when", decision.criterion)
            self.assertEqual(len(decision.alternatives_considered), 3)
        self.assertEqual(
            result.agent_decisions[-1].outcome,
            "stop_sufficient:sufficient",
        )

    def test_loop_budget_and_tool_retry_budget_are_isolated_without_bypass(
        self,
    ) -> None:
        exhausted: list[str] = []
        state = self._state()
        retry_budget = RetryBudget(max_retries=10)

        def step(state: ResearchState, context) -> LoopIterationResult:
            self.assertGreater(context.remaining_budget, 0)
            self.assertTrue(retry_budget.consume())
            state.metadata["progress"] += 1
            return LoopIterationResult(
                budget_consumed=1,
                retry_budget_consumed=1,
            )

        result = BoundedLoop(
            self._spec(exhausted, budget_ceiling=2),
            step,
        ).run(state)

        self.assertEqual(retry_budget.consumed, 2)
        self.assertEqual(result.agent_decisions[-1].inputs["budget_used"], 2)
        self.assertEqual(
            result.agent_decisions[-1].inputs["retry_budget_consumed"],
            1,
        )
        self.assertEqual(exhausted, ["budget_ceiling"])

        callback_called = False

        def forbidden_step(_state: ResearchState, _context) -> LoopIterationResult:
            nonlocal callback_called
            callback_called = True
            return LoopIterationResult(budget_consumed=0)

        BoundedLoop(
            self._spec([], budget_ceiling=0),
            forbidden_step,
        ).run(self._state())
        self.assertFalse(callback_called)


if __name__ == "__main__":
    unittest.main()
