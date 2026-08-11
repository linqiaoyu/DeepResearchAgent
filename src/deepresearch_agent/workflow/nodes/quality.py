"""Extraction, critique, and reflection nodes."""

from __future__ import annotations

from typing import Any

from deepresearch_agent.decisions import record_agent_decision
from deepresearch_agent.memory import ProceduralRecord, ProceduralSufficiencyResult
from deepresearch_agent.observability import record_component_activity
from deepresearch_agent.schemas import AgentDecision, ResearchState, utc_now
from deepresearch_agent.tools import classify_subquestion
from deepresearch_agent.trajectory import (
    LLMCallTrace,
    MemoryWriteTrace,
    SignalReadTrace,
    TrajectoryRecorder,
    active_trajectory_recorder,
)
from langgraph.graph import END

ResearchGraphState = dict[str, Any]


class QualityNodes:
    """Nodes that extract evidence, critique it, and reflect on the run."""

    def _extractor_node(self, graph_state: ResearchGraphState) -> ResearchGraphState:
        state = self._state_from_graph_values(graph_state)
        if self.settings.extractor_enabled:
            before_count = len(state.evidence_store)
            self._extracting(state)
            record_component_activity(
                state,
                component="extractor",
                enabled=True,
                status="completed",
                inputs={"source_count": len(state.sources)},
                outputs={
                    "evidence_before": before_count,
                    "evidence_after": len(state.evidence_store),
                },
            )
        else:
            record_component_activity(
                state,
                component="extractor",
                enabled=False,
                status="bypassed",
                inputs={"source_count": len(state.sources)},
                outputs={
                    "researcher_evidence_preserved": len(
                        state.evidence_store
                    )
                },
            )
        return self._state_output(
            self._complete_phase(state, graph_state, completed_phase="extracting", next_phase="critiquing")
        )

    def _route_after_extraction(self, graph_state: ResearchGraphState) -> str:
        return END if self._state_from_graph_values(graph_state).status == "paused" else "critic"

    def _critic_node(self, graph_state: ResearchGraphState) -> ResearchGraphState:
        state = self._state_from_graph_values(graph_state)
        if not state.plan:
            raise ValueError("Critiquing requires a plan.")
        if not self.settings.critic_enabled:
            state.critic_report = None
            state.retry_queue = []
            record_component_activity(
                state,
                component="critic",
                enabled=False,
                status="bypassed",
                inputs={"evidence_count": len(state.evidence_store)},
                outputs={"retry_tasks": 0, "issues": 0},
            )
            return self._state_output(
                self._complete_phase(
                    state,
                    graph_state,
                    completed_phase="critiquing",
                    next_phase="reporting",
                )
            )
        state.critic_report = self.critic.critique(state)
        state.critic_iteration = state.critic_report.iteration
        state.retry_queue = state.critic_report.retry_tasks
        if not state.critic_report.passed and state.critic_iteration >= self.settings.max_critic_iter:
            state.critic_report.forced_pass = True
            state.critic_report.passed = True
        record_component_activity(
            state,
            component="critic",
            enabled=True,
            status="completed",
            inputs={"evidence_count": len(state.evidence_store)},
            outputs={
                "issues": len(state.critic_report.issues),
                "retry_tasks": len(state.critic_report.retry_tasks),
                "passed": state.critic_report.passed,
                "forced_pass": state.critic_report.forced_pass,
                "iteration": state.critic_report.iteration,
            },
        )
        if state.critic_report.passed:
            return self._state_output(
                self._complete_phase(state, graph_state, completed_phase="critiquing", next_phase="reporting")
            )
        state.current_phase = "critiquing"
        state.status = "running"
        state.updated_at = utc_now()
        return self._state_output(state)

    def _route_after_critic(self, graph_state: ResearchGraphState) -> str:
        state = self._state_from_graph_values(graph_state)
        if state.status == "paused":
            return END
        if not self.settings.critic_enabled:
            if self.settings.research_loop_active:
                return "research_loop_decide"
            return (
                "reflector"
                if self.settings.reflection_enabled
                else "reporter"
            )
        if state.critic_report and state.critic_report.passed:
            if self.settings.research_loop_active:
                return "research_loop_decide"
            return (
                "reflector"
                if self.settings.reflection_enabled
                else "reporter"
            )
        return "retry_prepare"

    def _reflector_node(
        self,
        graph_state: ResearchGraphState,
    ) -> ResearchGraphState:
        state = self._state_from_graph_values(graph_state)
        recorder = active_trajectory_recorder()
        if recorder is None:
            raise RuntimeError(
                "REFLECTION_ENABLED requires a run-scoped AgentTrajectory"
            )
        trajectory = recorder.trajectory.model_copy(deep=True)
        decisions = [
            item.model_copy(deep=True) for item in state.agent_decisions
        ]
        request = self.reflector.reasoning_request(
            trajectory,
            decisions,
        )
        result = self.reflector.reflect(
            trajectory,
            decisions,
            reasoning_request=request,
        )
        signal_payload = result.deterministic_signals.model_dump(
            mode="json"
        )
        record_component_activity(
            state,
            component="reflector",
            enabled=True,
            status="completed",
            inputs={
                "trajectory_nodes": len(trajectory.node_transitions),
                "decisions": len(decisions),
            },
            outputs={
                "nonempty_signal_groups": sum(
                    int(bool(value))
                    for value in signal_payload.values()
                ),
                "llm_provider": result.llm_insight.provider,
                "llm_status": result.llm_insight.status,
            },
        )
        recorder.record_llm_call(
            LLMCallTrace(
                role="reflector_placeholder",
                prompt=[
                    {
                        "role": "user",
                        "content": request.model_dump_json(),
                    }
                ],
                response=result.llm_insight.model_dump_json(),
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                latency_seconds=0.0,
                model=result.llm_insight.provider or "unconfigured",
                attempt=1,
            )
        )
        signal_sources = {
            "persistent_weakness": (
                "ResearchState.agent_decisions.research_replan"
            ),
            "ineffective_source": "AgentTrajectory.tool_calls+node_transitions",
            "repeated_critic_issue": "AgentTrajectory.node_transitions.critic",
            "ineffective_replanning": (
                "ResearchState.agent_decisions.bounded_loop_control"
            ),
        }
        for signal_type, source in signal_sources.items():
            recorder.record_signal_read(
                SignalReadTrace(
                    signal_type=signal_type,
                    source=source,
                    keys=("iteration", "type", "count"),
                )
            )
        record_agent_decision(
            state,
            self.reflector.signal_extraction_decision(
                recorder.trajectory,
                state.agent_decisions,
                result.deterministic_signals,
            ),
        )
        self._write_procedural_memory(
            state,
            result.deterministic_signals,
            recorder,
        )
        state.metadata["reflection_result"] = result.model_dump(mode="json")
        if result.llm_insight.must_stop:
            state.status = "paused"
            state.metadata["reflection_cache_miss"] = {
                "cache_key": result.llm_insight.cache_key,
                "reason": result.llm_insight.cache_miss_reason,
            }
        return self._state_output(state)

    def _write_procedural_memory(
        self,
        state: ResearchState,
        signals,
        recorder: TrajectoryRecorder | None,
    ) -> None:
        if not state.plan or not self.settings.procedural_memory_enabled:
            record_component_activity(
                state,
                component="procedural_memory_write",
                enabled=self.settings.procedural_memory_enabled,
                status="bypassed",
                inputs={"has_plan": bool(state.plan)},
                outputs={"records_written": 0},
            )
            return
        raw_sufficiency = state.metadata.get("research_sufficiency", {})
        rows = (
            raw_sufficiency.get("by_sub_question", [])
            if isinstance(raw_sufficiency, dict)
            else []
        )
        sufficiency_by_id = {
            str(item.get("sub_question_id")): item
            for item in rows
            if isinstance(item, dict)
        }
        iteration = int(
            state.metadata.get("research_loop_tracker", {}).get(
                "iteration",
                0,
            )
        )
        written: list[dict[str, object]] = []
        for sub_question in state.plan.sub_questions:
            raw_result = sufficiency_by_id.get(sub_question.id, {})
            gaps = tuple(str(item) for item in raw_result.get("gaps", []))
            score = round(1.0 - len(gaps) / 6, 6)
            record = ProceduralRecord(
                question_type=classify_subquestion(sub_question),
                strategy=tuple(sub_question.search_queries),
                sufficiency_result=ProceduralSufficiencyResult(
                    score=score,
                    sufficient=bool(raw_result.get("sufficient", False)),
                    gaps=gaps,
                ),
                reflection_signals=signals,
                run_id=state.research_id,
                sub_question_id=sub_question.id,
                iteration=iteration,
                observed_as_of=self.research_as_of,
                provenance_refs=(f"run:{state.research_id}",),
            )
            self.procedural_memory.write(record)
            key = {
                "question_type": record.question_type,
                "run_id": record.run_id,
                "sub_question_id": record.sub_question_id,
                "iteration": record.iteration,
            }
            if recorder is not None:
                recorder.record_memory_write(
                    MemoryWriteTrace(
                    memory_type="procedural",
                    lifecycle=self.procedural_memory.lifecycle,
                    key=key,
                    value_summary={
                        "strategy": list(record.strategy),
                        "sufficiency_score": (
                            record.sufficiency_result.score
                        ),
                        "sufficient": (
                            record.sufficiency_result.sufficient
                        ),
                        "validation_status": record.validation_status,
                    },
                    )
                )
            written.append(key)
        record_agent_decision(
            state,
            AgentDecision(
                decision_type="procedural_memory_write",
                made_by="MemoryLifecycleController",
                inputs={
                    "records": written,
                    "lifecycle": self.procedural_memory.lifecycle,
                    "index_key": "question_type",
                },
                criterion=(
                    "write deterministic strategy-effect observations under "
                    "the MemoryStore cross_run scope without selecting a "
                    "future strategy"
                ),
                outcome=f"procedural_records_written={len(written)}",
                alternatives_considered=[
                    "skip_empty_signal_records",
                    "auto_select_historical_strategy",
                    "store_observation_without_auto_selection",
                ],
                iteration=iteration,
            ),
        )
        record_component_activity(
            state,
            component="procedural_memory_write",
            enabled=True,
            status="completed",
            inputs={"sub_questions": len(state.plan.sub_questions)},
            outputs={"records_written": len(written)},
        )
