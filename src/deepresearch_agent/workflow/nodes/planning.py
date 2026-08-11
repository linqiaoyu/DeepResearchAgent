"""Planning and memory application nodes."""

from __future__ import annotations

from typing import Any

from deepresearch_agent.decisions import record_agent_decision
from deepresearch_agent.memory import (
    EpisodicQuery,
    ProceduralQuery,
    classify_subquestions_from_prior,
)
from deepresearch_agent.observability import record_component_activity
from deepresearch_agent.orchestration import (
    build_decision_context,
    make_parallel_execution_plan,
)
from deepresearch_agent.research_snapshot import ResearchSnapshot, research_question_id
from deepresearch_agent.schemas import AgentDecision, ResearchState, TodoItem
from deepresearch_agent.tools import classify_subquestion
from deepresearch_agent.trajectory import active_trajectory_recorder
from langgraph.graph import END

ResearchGraphState = dict[str, Any]


class PlanningNodes:
    """Planner node and its episodic/procedural memory helpers."""

    def _planner_node(self, graph_state: ResearchGraphState) -> ResearchGraphState:
        state = self._state_from_graph_values(graph_state)
        self._planning(state)
        return self._state_output(
            self._complete_phase(state, graph_state, completed_phase="planning", next_phase="researching")
        )

    def _route_after_planning(self, graph_state: ResearchGraphState) -> str:
        return END if self._state_from_graph_values(graph_state).status == "paused" else "research_prepare"

    def _planning(self, state: ResearchState) -> None:
        state.plan = self.planner.plan(state.topic, state.depth_level, research_id=state.research_id)
        self._apply_procedural_memory(state)
        recorder = active_trajectory_recorder()
        if recorder:
            recorder.trajectory.request["recorded_plan"] = (
                state.plan.model_dump(mode="json")
            )
        selected_prior_snapshot: ResearchSnapshot | None = None
        if self.settings.prior_memory_enabled:
            prior_records = [
                item
                for item in self.episodic_memory.query(
                    EpisodicQuery(
                        question_id=research_question_id(state.topic),
                    )
                )
                if item.snapshot.as_of < self.research_as_of
            ]
            if prior_records:
                prior = prior_records[-1].snapshot
                selected_prior_snapshot = prior
                classify_subquestions_from_prior(
                    state,
                    prior,
                    watch_confidence_threshold=(
                        self.settings.prior_watch_confidence_threshold
                    ),
                    decision_context=(
                        build_decision_context(state, iteration=0)
                        if self.settings.decision_weaving_enabled
                        else None
                    ),
                )
            record_component_activity(
                state,
                component="episodic_memory",
                enabled=True,
                status="completed",
                inputs={"question_id": research_question_id(state.topic)},
                outputs={"records_read": len(prior_records)},
            )
        else:
            record_component_activity(
                state,
                component="episodic_memory",
                enabled=False,
                status="bypassed",
                inputs={"question_id": research_question_id(state.topic)},
                outputs={"records_read": 0},
            )
        if recorder and self.settings.prior_memory_enabled:
            recorder.trajectory.request["prior_memory_snapshot"] = (
                selected_prior_snapshot.model_dump(mode="json")
                if selected_prior_snapshot
                else None
            )
        if self.settings.execution_mode == "llm":
            state.metadata.setdefault("llm_stats", {})["planner"] = self.planner.last_stats
        planning_rejections = self.planner.last_stats.get(
            "structured_request_rejections",
            [],
        )
        if planning_rejections:
            state.metadata["structured_request_rejections"] = planning_rejections
        state.todo_list = [
            TodoItem(id=item.id, title=item.question, status="pending")
            for item in state.plan.sub_questions
        ]
        state.pending_tasks = [item.id for item in state.plan.sub_questions]
        execution_plan = make_parallel_execution_plan(
            plan_id=state.research_id,
            tasks=[(item.id, item.question) for item in state.plan.sub_questions],
            max_calls_per_step=(
                self.settings.branch_single_cap
                * (
                    self.settings.research_loop_max_iterations
                    if self.settings.research_loop_active
                    else 1
                )
            ),
            max_tokens=self.settings.token_budget,
            max_cost_cny=self.settings.llm_budget_cny,
        )
        state.metadata["execution_plan"] = execution_plan.model_dump(mode="json")

    def _apply_procedural_memory(self, state: ResearchState) -> None:
        """Adopt only an observed sufficient strategy for the same question type."""
        if not state.plan or not self.settings.procedural_memory_enabled:
            record_component_activity(
                state,
                component="procedural_memory_read",
                enabled=self.settings.procedural_memory_enabled,
                status="bypassed",
                inputs={"has_plan": bool(state.plan)},
                outputs={
                    "records_read": 0,
                    "strategies_adopted": 0,
                },
            )
            return
        records_read = 0
        strategies_adopted = 0
        for index, sub_question in enumerate(state.plan.sub_questions):
            history = self.procedural_memory.query(
                ProceduralQuery(question_type=classify_subquestion(sub_question))
            )
            records_read += len(history.records)
            candidates = [
                record for record in history.records
                if record.sufficiency_result.sufficient and record.strategy
            ]
            if not candidates:
                continue
            selected = max(
                candidates,
                key=lambda record: (
                    record.sufficiency_result.score,
                    record.run_id,
                    record.sub_question_id,
                    record.iteration,
                    record.strategy,
                ),
            )
            if tuple(sub_question.search_queries) == selected.strategy:
                continue
            state.plan.sub_questions[index] = sub_question.model_copy(
                update={"search_queries": list(selected.strategy)}
            )
            strategies_adopted += 1
            record_agent_decision(
                state,
                AgentDecision(
                    decision_type="procedural_memory_read",
                    made_by="PlannerAgent",
                    inputs={
                        "question_type": history.question_type,
                        "records_considered": len(history.records),
                        "prior_queries": sub_question.search_queries,
                    },
                    criterion=(
                        "adopt the highest-scoring sufficient observed strategy "
                        "for the exact deterministic question type"
                    ),
                    outcome=f"adopted_queries={list(selected.strategy)}",
                    alternatives_considered=[
                        "keep_current_queries",
                        "use_insufficient_observation",
                    ],
                ),
            )
        record_component_activity(
            state,
            component="procedural_memory_read",
            enabled=True,
            status="completed",
            inputs={"sub_questions": len(state.plan.sub_questions)},
            outputs={
                "records_read": records_read,
                "strategies_adopted": strategies_adopted,
            },
        )
