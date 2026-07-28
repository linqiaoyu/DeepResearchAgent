"""Research fan-out nodes for the workflow engine."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from deepresearch_agent.decisions import record_agent_decision
from deepresearch_agent.orchestration import BranchBudget, LoopTracker, RunScope
from deepresearch_agent.schemas import AgentDecision, Evidence, SearchRecord, Source, SubQuestion
from deepresearch_agent.tools import FIXED_CAPABILITY_SET
from langgraph.graph import END
from langgraph.types import Send

ResearchGraphState = dict[str, Any]


class ResearchNodes:
    """Node methods that prepare, fan out, and join primary research."""

    def _research_prepare_node(
        self, graph_state: ResearchGraphState, *, run_scope: RunScope
    ) -> ResearchGraphState:
        state = self._state_from_graph_values(graph_state)
        if not state.plan:
            raise ValueError("Researching requires a plan.")
        branch_ids = [item.id for item in state.plan.sub_questions]
        if self.settings.dynamic_capability_enabled:
            state.metadata["capability_selections"] = {
                item.id: self.capability_selector.select(
                    state,
                    item,
                ).model_dump(mode="json")
                for item in state.plan.sub_questions
            }
        if self.settings.research_loop_active:
            raw_tracker = state.metadata.get("research_loop_tracker")
            if not isinstance(raw_tracker, dict):
                tracker = self.research_loop.start(state)
                state.metadata["research_loop_tracker"] = asdict(tracker)
            else:
                tracker = LoopTracker(**raw_tracker)
            round_number = tracker.iteration + 1
            intents = state.metadata.setdefault("research_intents", [])
            if not any(
                item.get("iteration") == round_number
                for item in intents
                if isinstance(item, dict)
            ):
                intents.append(
                    {
                        "iteration": round_number,
                        "queries": {
                            item.id: list(item.search_queries)
                            for item in state.plan.sub_questions
                        },
                    }
                )
        if self._branch_budget_enabled() and run_scope.branch_budget is None:
            total_budget = (
                self.settings.research_loop_budget_ceiling
                if self.settings.research_loop_active
                else self.settings.branch_total_budget
            )
            run_scope.branch_budget = BranchBudget(
                total_budget=total_budget,
                per_branch_cap=self.settings.branch_single_cap,
            )
            allocations = run_scope.branch_budget.allocate(branch_ids, state)
            state.metadata["branch_budget"] = {
                "unit": "search_calls",
                "total_budget": total_budget,
                "per_branch_cap": self.settings.branch_single_cap,
                "allocations": run_scope.branch_budget.snapshot(),
                "phase": "before_send",
            }
            state.metadata["branch_budget"]["allocated_calls"] = allocations
        return {
            "research_state": self._dump_state(state),
            "active_sub_question_ids": branch_ids,
        }

    def _send_research_tasks(self, graph_state: ResearchGraphState) -> list[Send] | str:
        state = self._state_from_graph_values(graph_state)
        if not state.plan:
            raise ValueError("Researching requires a plan.")
        sends = [
            Send(
                "research_one",
                {
                    "research_state": graph_state["research_state"],
                    "fanout_sub_question": sub_question.model_dump(mode="json"),
                },
            )
            for sub_question in state.plan.sub_questions
        ]
        return sends or "research_join"

    def _research_one_node(
        self, graph_state: ResearchGraphState, *, run_scope: RunScope
    ) -> ResearchGraphState:
        state = self._state_from_graph_values(graph_state)
        sub_question = SubQuestion.model_validate(graph_state["fanout_sub_question"])
        selected_capabilities = set(FIXED_CAPABILITY_SET)
        if self.settings.dynamic_capability_enabled:
            raw_selections = state.metadata.get(
                "capability_selections",
                {},
            )
            raw_selection = (
                raw_selections.get(sub_question.id, {})
                if isinstance(raw_selections, dict)
                else {}
            )
            selected_capabilities = set(
                raw_selection.get("selected_capabilities", [])
                if isinstance(raw_selection, dict)
                else []
            )
        priority_urls: list[str] = []
        if self.settings.prior_memory_enabled:
            prior_metadata = state.metadata.get("prior_memory", {})
            classifications = (
                prior_metadata.get("classifications", [])
                if isinstance(prior_metadata, dict)
                else []
            )
            priority_urls = next(
                (
                    list(item.get("priority_urls", []))
                    for item in classifications
                    if isinstance(item, dict)
                    and item.get("sub_question_id") == sub_question.id
                    and item.get("kind") == "verify"
                ),
                [],
            )
        if "web_fetch" not in selected_capabilities:
            priority_urls = []
        if "structured_data_provider" in selected_capabilities:
            structured_evidence, structured_stats, symbol_resolutions = (
                self.researcher.structured_evidence(state.research_id, sub_question)
            )
        else:
            structured_evidence = []
            structured_stats = {
                "requests": len(
                    sub_question.structured_data_requests
                ),
                "executed_requests": 0,
                "records": 0,
                "symbol_resolution_failures": 0,
                "execution_failures": 0,
            }
            symbol_resolutions = []
        budget_metadata = state.metadata.get("branch_budget", {})
        allocated_calls = budget_metadata.get("allocated_calls", {})
        if self._branch_budget_enabled() and isinstance(
            allocated_calls,
            dict,
        ):
            allocation = int(allocated_calls.get(sub_question.id, 0))
            (
                sources,
                records,
                search_calls,
                branch_exhausted,
                source_decisions,
            ) = self.researcher.research_with_budget(
                sub_question,
                run_scope=run_scope,
                max_search_calls=allocation,
                priority_urls=priority_urls,
                enable_web_search=(
                    "web_search" in selected_capabilities
                ),
                enable_web_fetch="web_fetch" in selected_capabilities,
                source_decision_enabled=self.settings.dynamic_capability_enabled,
                enable_disclosure=(
                    "disclosure_source" in selected_capabilities
                ),
            )
        elif (
            priority_urls
            or "web_fetch" in selected_capabilities
            or self.settings.dynamic_capability_enabled
        ):
            (
                sources,
                records,
                search_calls,
                branch_exhausted,
                source_decisions,
            ) = self.researcher.research_with_budget(
                sub_question,
                run_scope=run_scope,
                max_search_calls=None,
                priority_urls=priority_urls,
                enable_web_search=(
                    "web_search" in selected_capabilities
                ),
                enable_web_fetch="web_fetch" in selected_capabilities,
                source_decision_enabled=self.settings.dynamic_capability_enabled,
                enable_disclosure=(
                    "disclosure_source" in selected_capabilities
                ),
            )
        else:
            if "web_search" in selected_capabilities:
                sources, records = self.researcher.research(sub_question, run_scope=run_scope)
                search_calls = len(records)
                branch_exhausted = False
                source_decisions = []
            else:
                sources = []
                records = []
                search_calls = 0
                branch_exhausted = False
                source_decisions = []
        output: ResearchGraphState = {
            "research_sources": {
                sub_question.id: [source.model_dump(mode="json") for source in sources]
            },
            "research_records": {
                sub_question.id: [record.model_dump(mode="json") for record in records]
            },
            "research_structured_evidence": {
                sub_question.id: [item.model_dump(mode="json") for item in structured_evidence]
            },
            "research_structured_stats": {
                sub_question.id: structured_stats
            },
            "research_symbol_resolutions": {
                sub_question.id: symbol_resolutions
            },
            "research_decisions": {
                sub_question.id: [
                    item.model_dump(mode="json")
                    for item in source_decisions
                ]
            },
        }
        if self._branch_budget_enabled():
            output["research_budget_usage"] = {
                sub_question.id: search_calls,
            }
            output["research_branch_coverage"] = {
                sub_question.id: {
                    "budget_exhausted": branch_exhausted,
                    "search_calls": search_calls,
                }
            }
        return output

    def _research_join_node(
        self, graph_state: ResearchGraphState, *, run_scope: RunScope
    ) -> ResearchGraphState:
        state = self._state_from_graph_values(graph_state)
        if not state.plan:
            raise ValueError("Researching requires a plan.")
        source_by_url: dict[str, Source] = {source.url: source for source in state.sources}
        sources_by_subquestion = dict(state.metadata.get("sources_by_subquestion", {}))
        source_batches = graph_state.get("research_sources", {})
        record_batches = graph_state.get("research_records", {})
        structured_batches = graph_state.get("research_structured_evidence", {})
        structured_stats_batches = graph_state.get("research_structured_stats", {})
        symbol_resolution_batches = graph_state.get("research_symbol_resolutions", {})
        decision_batches = graph_state.get("research_decisions", {})
        budget_usage = graph_state.get("research_budget_usage", {})
        branch_coverage = graph_state.get("research_branch_coverage", {})
        evidence_by_id = {item.id: item for item in state.evidence_store}

        for sub_question in state.plan.sub_questions:
            for item in decision_batches.get(sub_question.id, []):
                record_agent_decision(state, AgentDecision.model_validate(item))

        for sub_question in state.plan.sub_questions:
            sources = [
                Source.model_validate(item)
                for item in source_batches.get(sub_question.id, [])
            ]
            records = [
                SearchRecord.model_validate(item)
                for item in record_batches.get(sub_question.id, [])
            ]
            state.search_records.extend(records)
            for item in structured_batches.get(sub_question.id, []):
                evidence = Evidence.model_validate(item)
                evidence_by_id[evidence.id] = evidence
            sources_by_subquestion[sub_question.id] = [source.url for source in sources]
            for source in sources:
                source_by_url[source.url] = source
            if sub_question.id not in state.completed_tasks:
                state.completed_tasks.append(sub_question.id)

        state.sources = list(source_by_url.values())
        state.evidence_store = self._sorted_evidence(list(evidence_by_id.values()))
        state.metadata["sources_by_subquestion"] = sources_by_subquestion
        state.metadata["structured_data_stats"] = structured_stats_batches
        state.metadata["symbol_resolutions"] = symbol_resolution_batches
        structured_failures = [
            {"sub_question_id": sub_question_id, **failure}
            for sub_question_id, stats in structured_stats_batches.items()
            if isinstance(stats, dict)
            for failure in stats.get("failures", [])
            if isinstance(failure, dict)
        ]
        if structured_failures:
            state.metadata.setdefault("degradation_events", []).extend(
                {
                    "tool": "structured_data_provider",
                    "reason": "structured_data_execution_failure",
                    "impact": "structured evidence unavailable for a requested capability",
                    "attempts": 1,
                    **failure,
                }
                for failure in structured_failures
            )
        if self._branch_budget_enabled() and run_scope.branch_budget:
            for sub_question in state.plan.sub_questions:
                used = int(budget_usage.get(sub_question.id, 0))
                run_scope.branch_budget.consume(sub_question.id, used, state)
            metrics = {
                sub_question.id: float(
                    len(source_batches.get(sub_question.id, []))
                    + len(structured_batches.get(sub_question.id, []))
                )
                for sub_question in state.plan.sub_questions
            }
            if not self.settings.research_loop_active:
                run_scope.branch_budget.reallocate(
                    metrics,
                    state,
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
                    "metrics": metrics,
                    "branch_coverage": branch_coverage,
                    "phase": "after_join",
                    "total_used": run_scope.branch_budget.total_used,
                }
            )
        state.pending_tasks = []
        for item in state.todo_list:
            item.status = "done"
        return self._state_output(
            self._complete_phase(state, graph_state, completed_phase="researching", next_phase="extracting")
        )

    def _route_after_research(self, graph_state: ResearchGraphState) -> str:
        return END if self._state_from_graph_values(graph_state).status == "paused" else "extractor"
