"""Reporting and evaluation nodes for the workflow engine."""

from __future__ import annotations

import time
from typing import Any

from deepresearch_agent.decisions import append_decision_chain
from deepresearch_agent.orchestration import RunScope
from deepresearch_agent.reporting import (
    append_degradation_notice,
    append_prior_differences,
    append_research_process,
)
from deepresearch_agent.reflection import DeterministicReflectionSignals
from deepresearch_agent.schemas import utc_now
from deepresearch_agent.trajectory import active_trajectory_recorder
from langgraph.graph import END

ResearchGraphState = dict[str, Any]


class DeliveryNodes:
    """Nodes that assemble and evaluate the final research output."""

    def _reporter_node(
        self, graph_state: ResearchGraphState, *, run_scope: RunScope
    ) -> ResearchGraphState:
        state = self._state_from_graph_values(graph_state)
        if (
            self.settings.decision_weaving_enabled
            or self.settings.numeric_check_enabled
            or self.settings.dynamic_capability_enabled
        ):
            state.metadata["stable_reader_evidence_refs"] = True
        self._sync_tool_degradation(state, run_scope=run_scope)
        state.evidence_store = self._sorted_evidence(state.evidence_store)
        if (
            self.settings.procedural_memory_enabled
            and not self.settings.reflection_enabled
        ):
            self._write_procedural_memory(
                state,
                DeterministicReflectionSignals(),
                active_trajectory_recorder(),
            )
        report_context = self.reporter_context_builder.build(
            state,
            enabled=self.settings.context_packer_enabled,
            budget=self.settings.reporter_context_token_budget,
            as_of=self.settings.as_of,
        )
        state.final_report = self.reporter.report(
            state,
            context_evidence=list(report_context.evidence),
        )
        if self.settings.structured_output_enabled:
            state.structured_output = self.reporter.structured_output(state)
        if self.domain_pack.name != "finance":
            if self.settings.decision_weaving_enabled:
                state.final_report = append_decision_chain(
                    state.final_report, state.agent_decisions
                )
            state.final_report = append_degradation_notice(state.final_report, state)
            state.final_report = append_research_process(
                state.final_report,
                state,
                enabled=self.settings.research_loop_active,
            )
            state.final_report = append_prior_differences(
                state.final_report,
                state,
                enabled=self.settings.prior_memory_enabled,
            )
        # Finance execution traces belong to the audit bundle, not its short
        # reader report. They remain in ResearchState and are exported there.
        state.draft_report = state.final_report
        if self.settings.execution_mode == "llm":
            state.metadata.setdefault("llm_stats", {})["reporter"] = self.reporter.last_stats
            self._sync_llm_usage(state)
        return self._state_output(
            self._complete_phase(state, graph_state, completed_phase="reporting", next_phase="evaluating")
        )

    def _route_after_reporting(self, graph_state: ResearchGraphState) -> str:
        return END if self._state_from_graph_values(graph_state).status == "paused" else "evaluator"

    def _evaluator_node(self, graph_state: ResearchGraphState) -> ResearchGraphState:
        state = self._state_from_graph_values(graph_state)
        state.evidence_store = self._sorted_evidence(state.evidence_store)
        if self.settings.execution_mode == "llm":
            self._sync_llm_usage(state)
        state.evaluation = self.evaluator.evaluate(
            state,
            started_at=graph_state.get(
                "started_at",
                time.perf_counter(),
            ),
        )
        if self.settings.execution_mode == "llm":
            self._sync_llm_usage(state)
            state.evaluation = self.evaluator.refresh_operational_metrics(
                state.evaluation,
                state,
            )
        self.store.save_evaluation(state.evaluation)
        state.current_phase = "done"
        state.status = "paused" if graph_state.get("stop_after_phase") == "evaluating" else "done"
        state.updated_at = utc_now()
        return self._state_output(state)
