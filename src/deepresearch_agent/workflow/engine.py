from __future__ import annotations

import sqlite3
import time
from collections.abc import Sequence
from typing import Annotated, Any, TypedDict

from deepresearch_agent.agents import CriticAgent, Evaluator, ExtractorAgent, PlannerAgent, ReporterAgent, ResearcherAgent
from deepresearch_agent.llm import BudgetExceededError, LLMClient
from deepresearch_agent.schemas import (
    Evidence,
    ResearchState,
    RetryTask,
    SearchRecord,
    Source,
    SubQuestion,
    TodoItem,
    utc_now,
)
from deepresearch_agent.settings import Settings, load_settings
from deepresearch_agent.storage import SQLiteStore
from deepresearch_agent.tools import (
    SearchProvider,
    StructuredDataProvider,
    build_search_provider,
    build_structured_data_provider,
)
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send


def _merge_dicts(left: dict[str, Any] | None, right: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(left or {})
    merged.update(right or {})
    return merged


class ResearchGraphState(TypedDict, total=False):
    research_state: dict[str, Any]
    started_at: float
    stop_after_phase: str | None
    active_sub_question_ids: list[str]
    active_retry_task_ids: list[str]
    fanout_sub_question: dict[str, Any]
    fanout_retry_task: dict[str, Any]
    research_sources: Annotated[dict[str, list[dict[str, Any]]], _merge_dicts]
    research_records: Annotated[dict[str, list[dict[str, Any]]], _merge_dicts]
    research_structured_evidence: Annotated[dict[str, list[dict[str, Any]]], _merge_dicts]
    research_structured_stats: Annotated[dict[str, dict[str, int]], _merge_dicts]
    retry_sources: Annotated[dict[str, list[dict[str, Any]]], _merge_dicts]
    retry_records: Annotated[dict[str, dict[str, Any]], _merge_dicts]


class DeepResearchEngine:
    def __init__(
        self,
        settings: Settings | None = None,
        store: SQLiteStore | None = None,
        search_tool: SearchProvider | None = None,
        structured_data_provider: StructuredDataProvider | None = None,
    ) -> None:
        self.settings = settings or load_settings()
        self.store = store or SQLiteStore(self.settings.storage_path)
        self.search_tool = search_tool or build_search_provider()
        self.structured_data_provider = structured_data_provider or build_structured_data_provider()
        self.llm_client = (
            LLMClient(
                ledger_path=self.settings.llm_ledger_path,
                budget_cny=self.settings.llm_budget_cny,
            )
            if self.settings.execution_mode == "llm"
            else None
        )
        self.planner = PlannerAgent(llm_client=self.llm_client, settings=self.settings)
        self.researcher = ResearcherAgent(self.search_tool, self.structured_data_provider)
        self.extractor = ExtractorAgent(llm_client=self.llm_client)
        self.critic = CriticAgent()
        self.reporter = ReporterAgent(llm_client=self.llm_client)
        self.evaluator = Evaluator()
        self._checkpoint_conn = sqlite3.connect(self.settings.storage_path, check_same_thread=False)
        self.checkpointer = SqliteSaver(self._checkpoint_conn)
        self.graph = self._build_graph()

    def run(
        self,
        topic: str | None = None,
        depth_level: int = 2,
        research_id: str | None = None,
        resume: bool = False,
        stop_after_phase: str | None = None,
        interrupt_before: Sequence[str] | None = None,
        interrupt_after: Sequence[str] | None = None,
    ) -> ResearchState:
        started = time.perf_counter()
        if resume:
            if not research_id:
                raise ValueError("research_id is required when resume=True")
            state = self.load_state(research_id)
            if not state:
                raise ValueError(f"No checkpoint found for research_id={research_id}")
            state.status = "running"
            state.metadata["execution_mode"] = self.settings.execution_mode
            config = self._config(research_id)
            graph_input: ResearchGraphState | None = {
                "research_state": self._dump_state(state),
                "started_at": started,
                "stop_after_phase": stop_after_phase,
            }
            snapshot = self.graph.get_state(config)
            if snapshot.next:
                self.graph.update_state(config, graph_input)
                graph_input = None
        else:
            if not topic:
                raise ValueError("topic is required for a new research run")
            state = ResearchState(topic=topic, depth_level=depth_level)
            state.metadata["execution_mode"] = self.settings.execution_mode
            research_id = state.research_id
            config = self._config(research_id)
            graph_input = {
                "research_state": self._dump_state(state),
                "started_at": started,
                "stop_after_phase": stop_after_phase,
            }

        if self.llm_client:
            self.llm_client.start_run(research_id)
        try:
            result = self.graph.invoke(
                graph_input,
                config=config,
                interrupt_before=interrupt_before,
                interrupt_after=interrupt_after,
            )
        except BudgetExceededError:
            state = self.load_state(research_id) or state
            state.status = "budget_exceeded"
            state.metadata["llm_budget_exceeded"] = True
            state.metadata["llm_run_total_cny"] = self.llm_client.run_total_cny(research_id) if self.llm_client else 0.0
            self.graph.update_state(config, self._state_output(state))
            return state
        return self._state_from_graph_values(result)

    def load_state(self, research_id: str) -> ResearchState | None:
        snapshot = self.graph.get_state(self._config(research_id))
        if not snapshot.values or "research_state" not in snapshot.values:
            return None
        return self._state_from_graph_values(snapshot.values)

    def _build_graph(self):
        graph = StateGraph(ResearchGraphState)
        graph.add_node("entry", self._entry_node)
        graph.add_node("planner", self._planner_node)
        graph.add_node("research_prepare", self._research_prepare_node)
        graph.add_node("research_one", self._research_one_node)
        graph.add_node("research_join", self._research_join_node)
        graph.add_node("extractor", self._extractor_node)
        graph.add_node("critic", self._critic_node)
        graph.add_node("retry_prepare", self._retry_prepare_node)
        graph.add_node("retry_one", self._retry_one_node)
        graph.add_node("retry_join", self._retry_join_node)
        graph.add_node("reporter", self._reporter_node)
        graph.add_node("evaluator", self._evaluator_node)

        graph.add_edge(START, "entry")
        graph.add_conditional_edges("entry", self._route_entry)
        graph.add_conditional_edges("planner", self._route_after_planning)
        graph.add_conditional_edges("research_prepare", self._send_research_tasks)
        graph.add_edge("research_one", "research_join")
        graph.add_conditional_edges("research_join", self._route_after_research)
        graph.add_conditional_edges("extractor", self._route_after_extraction)
        graph.add_conditional_edges("critic", self._route_after_critic)
        graph.add_conditional_edges("retry_prepare", self._send_retry_tasks)
        graph.add_edge("retry_one", "retry_join")
        graph.add_edge("retry_join", "critic")
        graph.add_conditional_edges("reporter", self._route_after_reporting)
        graph.add_edge("evaluator", END)
        return graph.compile(checkpointer=self.checkpointer)

    def _entry_node(self, graph_state: ResearchGraphState) -> ResearchGraphState:
        return graph_state

    def _route_entry(self, graph_state: ResearchGraphState) -> str:
        state = self._state_from_graph_values(graph_state)
        if state.status == "done" or state.current_phase == "done":
            return END
        return {
            "planning": "planner",
            "researching": "research_prepare",
            "extracting": "extractor",
            "critiquing": "critic",
            "reporting": "reporter",
            "evaluating": "evaluator",
        }[state.current_phase]

    def _planner_node(self, graph_state: ResearchGraphState) -> ResearchGraphState:
        state = self._state_from_graph_values(graph_state)
        self._planning(state)
        return self._state_output(
            self._complete_phase(state, graph_state, completed_phase="planning", next_phase="researching")
        )

    def _route_after_planning(self, graph_state: ResearchGraphState) -> str:
        return END if self._state_from_graph_values(graph_state).status == "paused" else "research_prepare"

    def _research_prepare_node(self, graph_state: ResearchGraphState) -> ResearchGraphState:
        state = self._state_from_graph_values(graph_state)
        if not state.plan:
            raise ValueError("Researching requires a plan.")
        return {
            "research_state": self._dump_state(state),
            "active_sub_question_ids": [item.id for item in state.plan.sub_questions],
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

    def _research_one_node(self, graph_state: ResearchGraphState) -> ResearchGraphState:
        state = self._state_from_graph_values(graph_state)
        sub_question = SubQuestion.model_validate(graph_state["fanout_sub_question"])
        sources, records = self.researcher.research(sub_question)
        structured_evidence = self.researcher.structured_evidence(state.research_id, sub_question)
        return {
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
                sub_question.id: dict(self.researcher.last_structured_stats)
            },
        }

    def _research_join_node(self, graph_state: ResearchGraphState) -> ResearchGraphState:
        state = self._state_from_graph_values(graph_state)
        if not state.plan:
            raise ValueError("Researching requires a plan.")
        source_by_url: dict[str, Source] = {source.url: source for source in state.sources}
        sources_by_subquestion = dict(state.metadata.get("sources_by_subquestion", {}))
        source_batches = graph_state.get("research_sources", {})
        record_batches = graph_state.get("research_records", {})
        structured_batches = graph_state.get("research_structured_evidence", {})
        structured_stats_batches = graph_state.get("research_structured_stats", {})
        evidence_by_id = {item.id: item for item in state.evidence_store}

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
        state.pending_tasks = []
        for item in state.todo_list:
            item.status = "done"
        state.token_used += 1_500
        state.cost_used += 0.004
        return self._state_output(
            self._complete_phase(state, graph_state, completed_phase="researching", next_phase="extracting")
        )

    def _route_after_research(self, graph_state: ResearchGraphState) -> str:
        return END if self._state_from_graph_values(graph_state).status == "paused" else "extractor"

    def _extractor_node(self, graph_state: ResearchGraphState) -> ResearchGraphState:
        state = self._state_from_graph_values(graph_state)
        self._extracting(state)
        return self._state_output(
            self._complete_phase(state, graph_state, completed_phase="extracting", next_phase="critiquing")
        )

    def _route_after_extraction(self, graph_state: ResearchGraphState) -> str:
        return END if self._state_from_graph_values(graph_state).status == "paused" else "critic"

    def _critic_node(self, graph_state: ResearchGraphState) -> ResearchGraphState:
        state = self._state_from_graph_values(graph_state)
        if not state.plan:
            raise ValueError("Critiquing requires a plan.")
        state.critic_report = self.critic.critique(state)
        state.critic_iteration = state.critic_report.iteration
        state.retry_queue = state.critic_report.retry_tasks
        if not state.critic_report.passed and state.critic_iteration >= self.settings.max_critic_iter:
            state.critic_report.forced_pass = True
            state.critic_report.passed = True
        if state.critic_report.passed:
            state.token_used += 1_700 * max(state.critic_iteration, 1)
            state.cost_used += 0.005 * max(state.critic_iteration, 1)
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
        if state.critic_report and state.critic_report.passed:
            return "reporter"
        return "retry_prepare"

    def _retry_prepare_node(self, graph_state: ResearchGraphState) -> ResearchGraphState:
        state = self._state_from_graph_values(graph_state)
        return {
            "research_state": self._dump_state(state),
            "active_retry_task_ids": [task.id for task in state.retry_queue if not task.completed],
        }

    def _send_retry_tasks(self, graph_state: ResearchGraphState) -> list[Send] | str:
        state = self._state_from_graph_values(graph_state)
        active_ids = set(graph_state.get("active_retry_task_ids", []))
        sends = [
            Send(
                "retry_one",
                {
                    "research_state": graph_state["research_state"],
                    "fanout_retry_task": task.model_dump(mode="json"),
                },
            )
            for task in state.retry_queue
            if task.id in active_ids
        ]
        return sends or "retry_join"

    def _retry_one_node(self, graph_state: ResearchGraphState) -> ResearchGraphState:
        task = RetryTask.model_validate(graph_state["fanout_retry_task"])
        sources, record = self.researcher.retry(task.query, task.source_type)
        return {
            "retry_sources": {task.id: [source.model_dump(mode="json") for source in sources]},
            "retry_records": {task.id: record.model_dump(mode="json")},
        }

    def _retry_join_node(self, graph_state: ResearchGraphState) -> ResearchGraphState:
        state = self._state_from_graph_values(graph_state)
        if not state.plan:
            return self._state_output(state)
        source_by_url: dict[str, Source] = {source.url: source for source in state.sources}
        evidence_by_id = {item.id: item for item in state.evidence_store}
        active_ids = set(graph_state.get("active_retry_task_ids", []))
        source_batches = graph_state.get("retry_sources", {})
        record_batches = graph_state.get("retry_records", {})

        for task in state.retry_queue:
            if task.id not in active_ids:
                continue
            target_subq = self._retry_target_subquestion(state, task.sub_question_id)
            sources = [Source.model_validate(item) for item in source_batches.get(task.id, [])]
            record_data = record_batches.get(task.id)
            if record_data:
                state.search_records.append(SearchRecord.model_validate(record_data))
            for source in sources:
                source_by_url[source.url] = source
            extracted = self.extractor.extract(state.research_id, target_subq, sources)
            if self.settings.execution_mode == "llm":
                state.metadata.setdefault("llm_stats", {}).setdefault("extractor", []).append(
                    {"sub_question_id": target_subq.id, "retry_task_id": task.id, **self.extractor.last_stats}
                )
            for item in extracted:
                evidence_by_id[item.id] = item
            task.completed = True

        state.sources = list(source_by_url.values())
        state.evidence_store = self._sorted_evidence(list(evidence_by_id.values()))
        self.store.add_evidence_many(state.evidence_store)
        state.current_phase = "critiquing"
        state.status = "running"
        state.updated_at = utc_now()
        return self._state_output(state)

    def _reporter_node(self, graph_state: ResearchGraphState) -> ResearchGraphState:
        state = self._state_from_graph_values(graph_state)
        state.evidence_store = self._sorted_evidence(state.evidence_store)
        state.final_report = self.reporter.report(state)
        state.draft_report = state.final_report
        if self.settings.execution_mode == "llm":
            state.metadata.setdefault("llm_stats", {})["reporter"] = self.reporter.last_stats
            self._sync_llm_usage(state)
        else:
            state.token_used += self._estimate_tokens(state.final_report)
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
        state.evaluation = self.evaluator.evaluate(state, started_at=graph_state.get("started_at", time.perf_counter()))
        self.store.save_evaluation(state.evaluation)
        state.current_phase = "done"
        state.status = "paused" if graph_state.get("stop_after_phase") == "evaluating" else "done"
        state.updated_at = utc_now()
        return self._state_output(state)

    def _planning(self, state: ResearchState) -> None:
        state.plan = self.planner.plan(state.topic, state.depth_level, research_id=state.research_id)
        if self.settings.execution_mode == "llm":
            state.metadata.setdefault("llm_stats", {})["planner"] = self.planner.last_stats
        state.todo_list = [
            TodoItem(id=item.id, title=item.question, status="pending")
            for item in state.plan.sub_questions
        ]
        state.pending_tasks = [item.id for item in state.plan.sub_questions]
        state.token_used += 900
        state.cost_used += 0.002

    def _extracting(self, state: ResearchState) -> None:
        if not state.plan:
            raise ValueError("Extracting requires a plan.")
        evidence_by_id = {item.id: item for item in state.evidence_store}
        for sub_question in state.plan.sub_questions:
            relevant_sources = self._sources_for_subquestion(state, sub_question.id)
            extracted = self.extractor.extract(state.research_id, sub_question, relevant_sources)
            if self.settings.execution_mode == "llm":
                state.metadata.setdefault("llm_stats", {}).setdefault("extractor", []).append(
                    {"sub_question_id": sub_question.id, **self.extractor.last_stats}
                )
            for item in extracted:
                evidence_by_id[item.id] = item
        state.evidence_store = self._sorted_evidence(list(evidence_by_id.values()))
        self.store.add_evidence_many(state.evidence_store)
        state.token_used += 2_300
        state.cost_used += 0.006

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
            "total_cost_cny": round(float(aggregate["total_cost_cny"]), 8),
            "ledger_total_cny": round(self.llm_client.ledger_total_cny(), 8),
            "price_source": aggregate.get("price_source"),
        }

    def _config(self, research_id: str) -> dict[str, dict[str, str]]:
        return {"configurable": {"thread_id": research_id}}

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
