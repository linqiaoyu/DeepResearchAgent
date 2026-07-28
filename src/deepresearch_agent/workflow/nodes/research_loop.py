"""Research-loop decision and refinement nodes."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from deepresearch_agent.orchestration import (
    LoopIterationResult,
    LoopTracker,
    ResearchSufficiency,
    RunScope,
    build_decision_context,
    evaluate_research_sufficiency,
    refine_research_plan,
)
from deepresearch_agent.schemas import utc_now
from langgraph.graph import END

ResearchGraphState = dict[str, Any]


class ResearchLoopNodes:
    """Nodes that decide whether another research iteration is required."""

    def _route_after_reflection(
        self,
        graph_state: ResearchGraphState,
    ) -> str:
        state = self._state_from_graph_values(graph_state)
        if state.status == "paused":
            return END
        return (
            "research_refine"
            if state.metadata.get("research_loop_route") == "continue"
            else "reporter"
        )

    def _research_loop_decide_node(
        self,
        graph_state: ResearchGraphState,
        *,
        run_scope: RunScope,
    ) -> ResearchGraphState:
        state = self._state_from_graph_values(graph_state)
        sufficiency = evaluate_research_sufficiency(
            state,
            as_of=self.research_as_of,
            thresholds=self.sufficiency_thresholds,
        )
        state.metadata["research_loop_score"] = sufficiency.score
        if run_scope.branch_budget:
            branch_metrics = {
                item.sub_question_id: round(
                    1.0 - len(item.gaps) / 6,
                    6,
                )
                for item in sufficiency.by_sub_question
            }
            context = (
                build_decision_context(
                    state,
                    iteration=(
                        int(
                            state.metadata.get(
                                "research_loop_tracker",
                                {},
                            ).get("iteration", 0)
                        )
                        + 1
                    ),
                    budget_total=run_scope.branch_budget.total_budget,
                    budget_used=run_scope.branch_budget.total_used,
                    budget_snapshot=run_scope.branch_budget.snapshot(),
                    sufficiency=sufficiency,
                )
                if self.settings.decision_weaving_enabled
                else None
            )
            run_scope.branch_budget.reallocate(
                branch_metrics,
                state,
                decision_context=context,
                verify_min_allocation=(
                    self.settings.decision_weaving_verify_min_allocation
                    if context
                    else 0
                ),
            )
            state.metadata["branch_budget"].update(
                {
                    "allocations": run_scope.branch_budget.snapshot(),
                    "allocated_calls": {
                        branch_id: int(item["remaining"])
                        for branch_id, item in (
                            run_scope.branch_budget.snapshot().items()
                        )
                    },
                    "metrics": branch_metrics,
                    "phase": "after_sufficiency",
                    "total_used": run_scope.branch_budget.total_used,
                }
            )
        raw_tracker = state.metadata.get("research_loop_tracker")
        tracker = (
            LoopTracker(**raw_tracker)
            if isinstance(raw_tracker, dict)
            else self.research_loop.start(state)
        )
        budget_usage = graph_state.get("research_budget_usage", {})
        iteration_result = LoopIterationResult(
            budget_consumed=sum(
                int(value) for value in budget_usage.values()
            ),
            stop_requested=sufficiency.sufficient,
            stop_reason="sufficiency_thresholds_met",
        )
        loop_context = (
            build_decision_context(
                state,
                iteration=tracker.iteration + 1,
                budget_total=(
                    run_scope.branch_budget.total_budget
                    if run_scope.branch_budget
                    else self.settings.research_loop_budget_ceiling
                ),
                budget_used=(
                    run_scope.branch_budget.total_used
                    if run_scope.branch_budget
                    else tracker.budget_used
                ),
                budget_snapshot=(
                    run_scope.branch_budget.snapshot()
                    if run_scope.branch_budget
                    else None
                ),
                sufficiency=sufficiency,
            )
            if self.settings.decision_weaving_enabled
            else None
        )
        outcome = self.research_loop.advance(
            state,
            tracker,
            iteration_result,
            decision_context=loop_context,
            budget_remaining_ratio_threshold=(
                self.settings.decision_weaving_budget_remaining_ratio
                if loop_context
                else 0.0
            ),
        )
        state.metadata["research_loop_tracker"] = asdict(outcome.tracker)
        state.metadata["research_loop_route"] = outcome.route
        state.metadata["research_sufficiency"] = sufficiency.model_dump(
            mode="json"
        )
        process = state.metadata.setdefault("research_process", [])
        intent = next(
            (
                item
                for item in reversed(
                    state.metadata.get("research_intents", [])
                )
                if isinstance(item, dict)
                and item.get("iteration") == outcome.tracker.iteration
            ),
            {},
        )
        process.append(
            {
                "iteration": outcome.tracker.iteration,
                "queries": intent.get("queries", {}),
                "sufficiency": sufficiency.model_dump(mode="json"),
                "decision": state.agent_decisions[-1].model_dump(
                    mode="json"
                ),
                "budget": (
                    dict(state.metadata.get("branch_budget", {}))
                    if self._branch_budget_enabled()
                    else {}
                ),
                "stop_boundary": outcome.stop_boundary,
            }
        )
        return self._state_output(state)

    def _route_after_research_loop(
        self,
        graph_state: ResearchGraphState,
    ) -> str:
        state = self._state_from_graph_values(graph_state)
        if self.settings.reflection_enabled:
            return "reflector"
        return (
            "research_refine"
            if state.metadata.get("research_loop_route") == "continue"
            else "reporter"
        )

    def _research_refine_node(
        self,
        graph_state: ResearchGraphState,
        *,
        run_scope: RunScope,
    ) -> ResearchGraphState:
        state = self._state_from_graph_values(graph_state)
        raw_sufficiency = state.metadata.get("research_sufficiency")
        if not isinstance(raw_sufficiency, dict):
            raise ValueError("Research refinement requires sufficiency metrics")
        sufficiency = ResearchSufficiency.model_validate(raw_sufficiency)
        tracker = LoopTracker(
            **state.metadata["research_loop_tracker"],
        )
        refined = refine_research_plan(
            state,
            sufficiency,
            as_of=self.research_as_of,
            iteration=tracker.iteration + 1,
            decision_context=(
                build_decision_context(
                    state,
                    iteration=tracker.iteration + 1,
                    budget_total=(
                        run_scope.branch_budget.total_budget
                        if run_scope.branch_budget
                        else 0
                    ),
                    budget_used=(
                        run_scope.branch_budget.total_used
                        if run_scope.branch_budget
                        else 0
                    ),
                    budget_snapshot=(
                        run_scope.branch_budget.snapshot()
                        if run_scope.branch_budget
                        else None
                    ),
                    sufficiency=sufficiency,
                )
                if (
                    self.settings.decision_weaving_enabled
                    or self.settings.reflection_enabled
                )
                else None
            ),
        )
        state.metadata["next_research_intent"] = refined
        if self.settings.reflection_enabled:
            process = state.metadata.get("research_process", [])
            reflection_result = state.metadata.get(
                "reflection_result",
                {},
            )
            if process and isinstance(process[-1], dict):
                process[-1]["reflection_effect"] = {
                    "deterministic_signals": (
                        reflection_result.get(
                            "deterministic_signals",
                            {},
                        )
                        if isinstance(reflection_result, dict)
                        else {}
                    ),
                    "adjusted_queries": refined,
                    "llm_insight_used": False,
                }
        state.critic_report = None
        state.critic_iteration = 0
        state.retry_queue = []
        state.current_phase = "researching"
        state.status = "running"
        state.updated_at = utc_now()
        return self._state_output(state)
