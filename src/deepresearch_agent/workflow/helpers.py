"""Shared workflow state and extraction helpers."""

from __future__ import annotations

from typing import Any

from deepresearch_agent.orchestration import RunScope
from deepresearch_agent.schemas import Evidence, ResearchState, Source, SubQuestion, utc_now

ResearchGraphState = dict[str, Any]


class WorkflowHelpers:
    """State, extraction, and run-accounting helpers used by workflow nodes."""

    def _extracting(self, state: ResearchState) -> None:
        if not state.plan:
            raise ValueError("Extracting requires a plan.")
        evidence_by_id = {item.id: item for item in state.evidence_store}
        for sub_question in state.plan.sub_questions:
            relevant_sources = self._sources_for_subquestion(state, sub_question.id)
            extracted = self.extractor.extract(state.research_id, sub_question, relevant_sources)
            rejections = self.extractor.last_stats.get("authoritative_parse_rejections", [])
            if rejections:
                state.metadata.setdefault("authoritative_parse_rejections", []).extend(
                    [{"sub_question_id": sub_question.id, **item} for item in rejections]
                )
            ingress_events = self.extractor.last_stats.get(
                "content_ingress_events", []
            )
            if isinstance(ingress_events, list):
                state.metadata.setdefault("content_security_events", []).extend(
                    [
                        {"sub_question_id": sub_question.id, **item}
                        for item in ingress_events
                        if isinstance(item, dict)
                    ]
                )
            if self.settings.execution_mode == "llm":
                state.metadata.setdefault("llm_stats", {}).setdefault("extractor", []).append(
                    {"sub_question_id": sub_question.id, **self.extractor.last_stats}
                )
            for item in extracted:
                evidence_by_id[item.id] = item
        state.evidence_store = self._sorted_evidence(list(evidence_by_id.values()))
        self.store.add_evidence_many(state.evidence_store)

    def _retry_target_subquestion(
        self,
        state: ResearchState,
        sub_question_id: str | None,
    ) -> SubQuestion:
        if not state.plan or not state.plan.sub_questions:
            raise ValueError("Retry extraction requires a plan with sub-questions.")
        if sub_question_id:
            for sub_question in state.plan.sub_questions:
                if sub_question.id == sub_question_id:
                    return sub_question
        return state.plan.sub_questions[-1]

    def _sources_for_subquestion(self, state: ResearchState, sub_question_id: str) -> list[Source]:
        if not state.plan:
            return []
        source_urls = set(state.metadata.get("sources_by_subquestion", {}).get(sub_question_id, []))
        if source_urls:
            return [source for source in state.sources if source.url in source_urls]
        sub_question = next(item for item in state.plan.sub_questions if item.id == sub_question_id)
        query_text = " ".join([sub_question.question, *sub_question.search_queries]).lower()
        matches = [
            source for source in state.sources
            if any(term.lower() in f"{source.title} {source.content}".lower() for term in query_text.split()[:16])
        ]
        return matches[:4] or state.sources[:2]

    def _complete_phase(
        self,
        state: ResearchState,
        graph_state: ResearchGraphState,
        completed_phase: str,
        next_phase: str,
    ) -> ResearchState:
        state.current_phase = next_phase
        state.updated_at = utc_now()
        if graph_state.get("stop_after_phase") == completed_phase:
            state.status = "paused"
        else:
            state.status = "running"
        return state

    def _estimate_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)

    def _sync_llm_usage(self, state: ResearchState) -> None:
        if not self.llm_client:
            return
        aggregate = self.llm_client.aggregate_run(state.research_id)
        rows = aggregate["rows"]
        state.token_used = sum(int(row.get("total_tokens", 0)) for row in rows)
        state.cost_used = round(sum(float(row.get("cost_usd", 0.0)) for row in rows), 8)
        state.metadata["llm_usage"] = {
            "by_role": aggregate["by_role"],
            "structured_output": aggregate.get("structured_output", {}),
            "total_cost_cny": round(float(aggregate["total_cost_cny"]), 8),
            "ledger_total_cny": round(self.llm_client.ledger_total_cny(), 8),
            "price_source": aggregate.get("price_source"),
            "price_sources": aggregate.get("price_sources", []),
        }

    def _config(self, research_id: str) -> dict[str, Any]:
        return {
            "configurable": {"thread_id": research_id},
            "recursion_limit": max(
                25,
                self.settings.research_loop_max_iterations * 20 + 20,
            ),
        }

    def _branch_budget_enabled(self) -> bool:
        return (
            self.settings.branch_budget_enabled
            or self.settings.research_loop_active
        )

    def _on_research_loop_exhausted(
        self,
        state: ResearchState,
        boundary: str,
    ) -> None:
        state.metadata.setdefault("research_loop", {})[
            "convergence"
        ] = f"graceful_exhaustion:{boundary}"

    def _dump_state(self, state: ResearchState) -> dict[str, Any]:
        return state.model_dump(mode="json")

    def _state_output(self, state: ResearchState) -> ResearchGraphState:
        return {"research_state": self._dump_state(state)}

    def _state_from_graph_values(self, graph_state: ResearchGraphState | dict[str, Any]) -> ResearchState:
        state_data = graph_state.get("research_state")
        if state_data is None:
            raise ValueError("Graph state is missing research_state.")
        if isinstance(state_data, ResearchState):
            return state_data
        return ResearchState.model_validate(state_data)

    def _sorted_evidence(self, evidence: list[Evidence]) -> list[Evidence]:
        return sorted(
            evidence,
            key=lambda item: (item.sub_question_id, item.source_url, item.claim),
        )

    def _sync_tool_degradation(
        self, state: ResearchState, *, run_scope: RunScope
    ) -> None:
        # The run context is the source of truth for every registered tool.
        # Reading through web_search hid disclosure degradation behind an
        # unrelated adapter and failed when tool contracts were disabled.
        provider_events = (
            [
                event.model_dump(mode="json")
                for event in run_scope.tool_context.degradation_events
            ]
        )
        if not provider_events:
            return
        existing = list(state.metadata.get("degradation_events", []))
        signatures = {
            (
                str(item.get("tool")),
                str(item.get("reason")),
                str(item.get("impact")),
                int(item.get("attempts", 0)),
            )
            for item in existing
            if isinstance(item, dict)
        }
        for event in provider_events:
            if not isinstance(event, dict):
                continue
            signature = (
                str(event.get("tool")),
                str(event.get("reason")),
                str(event.get("impact")),
                int(event.get("attempts", 0)),
            )
            if signature not in signatures:
                existing.append(event)
                signatures.add(signature)
        state.metadata["degradation_events"] = existing
        summary: dict[str, int] = {}
        for event in existing:
            reason = str(event.get("reason", "unknown"))
            summary[reason] = summary.get(reason, 0) + 1
        state.metadata["tool_error_summary"] = summary
