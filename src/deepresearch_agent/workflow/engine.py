from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Sequence
from dataclasses import asdict
from typing import Annotated, Any, TypedDict
from urllib.parse import urlsplit

from deepresearch_agent.agents import CriticAgent, Evaluator, ExtractorAgent, PlannerAgent, ReporterAgent, ResearcherAgent
from deepresearch_agent.config_validation import validate_required_configuration
from deepresearch_agent.decisions import (
    append_decision_chain,
    record_agent_decision,
)
from deepresearch_agent.llm import BudgetExceededError, LLMClient
from deepresearch_agent.memory import (
    ContextWorkingMemory,
    EpisodicMemory,
    EpisodicQuery,
    ProceduralMemory,
    ProceduralRecord,
    ProceduralSufficiencyResult,
    WorkingMemoryQuery,
    WorkingMemoryWrite,
    classify_subquestions_from_prior,
    prior_difference_rows,
)
from deepresearch_agent.observability import JsonLogger, correlation_context
from deepresearch_agent.orchestration import (
    BoundedLoop,
    BranchBudget,
    ContractField,
    ContractGraph,
    ContractInvariant,
    NodeContract,
    LoopIterationResult,
    LoopSpec,
    LoopTracker,
    ResearchSufficiency,
    SufficiencyThresholds,
    build_decision_context,
    enforce_node_contract,
    evaluate_research_sufficiency,
    refine_research_plan,
    validate_contract_graph,
)
from deepresearch_agent.provenance import build_run_manifest, write_run_manifest
from deepresearch_agent.reflection import Reflector
from deepresearch_agent.research_snapshot import (
    ResearchSnapshot,
    research_question_id,
)
from deepresearch_agent.schemas import (
    AgentDecision,
    Evidence,
    ResearchState,
    RetryTask,
    SearchRecord,
    Source,
    SubQuestion,
    TodoItem,
    utc_now,
)
from deepresearch_agent.settings import Settings, load_settings, project_root
from deepresearch_agent.skills import (
    SkillPackLoader,
    finance_metric_skill_applicable,
    load_skills_if_enabled,
)
from deepresearch_agent.storage import SQLiteStore
from deepresearch_agent.tools import (
    CapabilityRegistry,
    DeterministicCapabilitySelector,
    FIXED_CAPABILITY_SET,
    SearchProvider,
    StructuredDataProvider,
    TrajectoryStructuredDataProvider,
    build_capability_registry,
    build_search_provider,
    build_structured_data_provider,
    classify_subquestion,
)
from deepresearch_agent.tools.contract_adapter import ContractSearchProvider
from deepresearch_agent.trajectory import (
    LLMCallTrace,
    MemoryWriteTrace,
    NodeTransitionTrace,
    SignalReadTrace,
    TrajectoryRecorder,
    active_trajectory_recorder,
    trajectory_recording,
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
    research_symbol_resolutions: Annotated[dict[str, list[dict[str, Any]]], _merge_dicts]
    research_decisions: Annotated[dict[str, list[dict[str, Any]]], _merge_dicts]
    research_budget_usage: Annotated[dict[str, int], _merge_dicts]
    research_branch_coverage: Annotated[dict[str, dict[str, Any]], _merge_dicts]
    retry_sources: Annotated[dict[str, list[dict[str, Any]]], _merge_dicts]
    retry_records: Annotated[dict[str, dict[str, Any]], _merge_dicts]


def _trace_graph_summary(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"type": type(value).__name__}
    raw_state = value.get("research_state", {})
    if hasattr(raw_state, "model_dump"):
        raw_state = raw_state.model_dump(mode="json")
    if not isinstance(raw_state, dict):
        raw_state = {}
    summary: dict[str, Any] = {
        "phase": raw_state.get("current_phase"),
        "status": raw_state.get("status"),
        "source_count": len(raw_state.get("sources", [])),
        "evidence_count": len(raw_state.get("evidence_store", [])),
        "retry_count": len(raw_state.get("retry_queue", [])),
    }
    evidence_domains = sorted(
        {
            urlsplit(str(item.get("source_url", ""))).netloc.lower()
            for item in raw_state.get("evidence_store", [])
            if isinstance(item, dict) and item.get("source_url")
        }
    )
    if evidence_domains:
        summary["evidence_source_domains"] = evidence_domains
    critic_report = raw_state.get("critic_report")
    if isinstance(critic_report, dict):
        issue_types = sorted(
            str(item.get("issue_type"))
            for item in critic_report.get("issues", [])
            if isinstance(item, dict) and item.get("issue_type")
        )
        if issue_types:
            summary["critic_issue_types"] = issue_types
    sub_question = value.get("fanout_sub_question")
    if isinstance(sub_question, dict):
        summary["sub_question_id"] = sub_question.get("id")
    retry_task = value.get("fanout_retry_task")
    if isinstance(retry_task, dict):
        summary["retry_task_id"] = retry_task.get("id")
    return summary


class DeepResearchEngine:
    def __init__(
        self,
        settings: Settings | None = None,
        store: SQLiteStore | None = None,
        search_tool: SearchProvider | None = None,
        structured_data_provider: StructuredDataProvider | None = None,
        episodic_memory: EpisodicMemory | None = None,
        procedural_memory: ProceduralMemory | None = None,
    ) -> None:
        self.settings = settings or load_settings()
        if self.settings.config_fail_fast_enabled:
            validate_required_configuration(self.settings)
        self.logger = JsonLogger(enabled=self.settings.structured_logging_enabled)
        self.store = store or SQLiteStore(self.settings.storage_path)
        configured_search_tool = search_tool or build_search_provider(
            as_of=self.settings.as_of
        )
        if self.settings.tool_contract_enabled:
            configured_search_tool = ContractSearchProvider(
                configured_search_tool,
                logger=self.logger,
            )
        configured_structured_provider = (
            structured_data_provider or build_structured_data_provider()
        )
        configured_structured_provider = (
            TrajectoryStructuredDataProvider(
                configured_structured_provider
            )
        )
        self.capability_registry: CapabilityRegistry = (
            build_capability_registry(
                search_provider=configured_search_tool,
                structured_data_provider=configured_structured_provider,
            )
        )
        self.skill_loader = SkillPackLoader(
            project_root() / "skills"
        )
        self.search_tool = self.capability_registry.resolve("web_search")
        self.structured_data_provider = self.capability_registry.resolve(
            "structured_data_provider"
        )
        self.capability_selector = (
            DeterministicCapabilitySelector.from_json(
                self.capability_registry,
                self.settings.dynamic_capability_rules_json,
            )
        )
        self.llm_client = (
            LLMClient(
                ledger_path=self.settings.llm_ledger_path,
                budget_cny=self.settings.llm_budget_cny,
                logger=self.logger,
            )
            if self.settings.execution_mode == "llm"
            else None
        )
        self.planner = PlannerAgent(llm_client=self.llm_client, settings=self.settings)
        self.researcher = ResearcherAgent(
            search_tool=self.capability_registry.resolve("web_search"),
            structured_data_provider=self.capability_registry.resolve(
                "structured_data_provider"
            ),
            max_searches_per_run=self.settings.max_searches_per_run,
            fetch_tool=self.capability_registry.resolve("web_fetch"),
        )
        self.extractor = ExtractorAgent(
            llm_client=self.llm_client,
            injection_guard_enabled=self.settings.injection_guard_enabled,
        )
        self.critic = CriticAgent(
            today=self.settings.as_of,
            injection_guard_enabled=self.settings.injection_guard_enabled,
            numeric_check_enabled=self.settings.numeric_check_enabled,
            numeric_relative_tolerance=(
                self.settings.numeric_check_relative_tolerance
            ),
            numeric_check_absolute_tolerance=(
                self.settings.numeric_check_absolute_tolerance
            ),
        )
        self.reporter = ReporterAgent(llm_client=self.llm_client)
        self.evaluator = Evaluator()
        self.reflector = Reflector()
        self.branch_budget: BranchBudget | None = None
        self.working_memory = ContextWorkingMemory()
        self.episodic_memory = episodic_memory or EpisodicMemory()
        self.procedural_memory = procedural_memory or ProceduralMemory()
        self.research_as_of = self.settings.as_of or self.critic.today
        self.sufficiency_thresholds = SufficiencyThresholds(
            min_evidence_count=self.settings.research_min_evidence_count,
            min_independent_domains=(
                self.settings.research_min_independent_domains
            ),
            min_average_confidence=(
                self.settings.research_min_average_confidence
            ),
            max_freshness_age_days=(
                self.settings.research_max_freshness_age_days
            ),
            max_unresolved_critic_issues=(
                self.settings.research_max_unresolved_critic_issues
            ),
        )
        self.research_loop = BoundedLoop(
            LoopSpec(
                max_iterations=self.settings.research_loop_max_iterations,
                budget_ceiling=self.settings.research_loop_budget_ceiling,
                no_progress_window=(
                    self.settings.research_loop_no_progress_window
                ),
                progress_metric=lambda state: float(
                    state.metadata.get("research_loop_score", 0.0)
                ),
                on_exhausted=self._on_research_loop_exhausted,
                budget_unit="calls",
            ),
            step=lambda _state, _context: LoopIterationResult(
                budget_consumed=0
            ),
        )
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
        manifest_started_at = utc_now()
        self.researcher.reset_search_budget()
        self.branch_budget = None
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

        with correlation_context(run_id=research_id, node="workflow"):
            self.logger.event("run_started", mode=self.settings.execution_mode)
            if self.llm_client:
                self.llm_client.start_run(research_id)
            recorder = (
                TrajectoryRecorder(
                    run_id=research_id,
                    request={
                        "topic": state.topic,
                        "depth_level": state.depth_level,
                        "as_of": (
                            self.settings.as_of.isoformat()
                            if self.settings.as_of
                            else None
                        ),
                        "mode": self.settings.execution_mode,
                        "strategy_config": {
                            "max_critic_iter": (
                                self.settings.max_critic_iter
                            ),
                            "branch_budget_enabled": (
                                self.settings.branch_budget_enabled
                            ),
                            "branch_total_budget": (
                                self.settings.branch_total_budget
                            ),
                            "branch_single_cap": (
                                self.settings.branch_single_cap
                            ),
                            "research_loop_enabled": (
                                self.settings.research_loop_enabled
                            ),
                            "research_loop_max_iterations": (
                                self.settings.research_loop_max_iterations
                            ),
                            "research_loop_budget_ceiling": (
                                self.settings.research_loop_budget_ceiling
                            ),
                            "research_loop_no_progress_window": (
                                self.settings.research_loop_no_progress_window
                            ),
                            "research_min_evidence_count": (
                                self.settings.research_min_evidence_count
                            ),
                            "research_min_independent_domains": (
                                self.settings.research_min_independent_domains
                            ),
                            "research_min_average_confidence": (
                                self.settings.research_min_average_confidence
                            ),
                            "research_max_freshness_age_days": (
                                self.settings.research_max_freshness_age_days
                            ),
                            "research_max_unresolved_critic_issues": (
                                self.settings.research_max_unresolved_critic_issues
                            ),
                            "decision_weaving_enabled": (
                                self.settings.decision_weaving_enabled
                            ),
                            "decision_weaving_budget_remaining_ratio": (
                                self.settings.decision_weaving_budget_remaining_ratio
                            ),
                            "decision_weaving_verify_min_allocation": (
                                self.settings.decision_weaving_verify_min_allocation
                            ),
                            "numeric_check_enabled": (
                                self.settings.numeric_check_enabled
                            ),
                            "numeric_check_relative_tolerance": (
                                self.settings.numeric_check_relative_tolerance
                            ),
                            "numeric_check_absolute_tolerance": (
                                self.settings.numeric_check_absolute_tolerance
                            ),
                            "dynamic_capability_enabled": (
                                self.settings.dynamic_capability_enabled
                            ),
                            "dynamic_capability_rules_json": (
                                self.settings.dynamic_capability_rules_json
                            ),
                            "reflection_enabled": (
                                self.settings.reflection_enabled
                            ),
                            "skill_packs_enabled": (
                                self.settings.skill_packs_enabled
                            ),
                        },
                    },
                )
                if (
                    self.settings.trajectory_record_enabled
                    or self.settings.reflection_enabled
                )
                else None
            )
            try:
                with trajectory_recording(recorder):
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
                state.metadata["llm_run_total_cny"] = (
                    self.llm_client.run_total_cny(research_id) if self.llm_client else 0.0
                )
                self.graph.update_state(config, self._state_output(state))
                self.logger.event("run_finished", status=state.status)
                return state
        state = self._state_from_graph_values(result)
        manifest_path = None
        if self.settings.run_manifest_enabled:
            try:
                manifest = build_run_manifest(
                    state,
                    self.settings,
                    started_at=manifest_started_at,
                )
                manifest_path = write_run_manifest(
                    manifest,
                    self.settings.runs_root,
                )
            except Exception as exc:
                state.metadata.setdefault("degradation_events", []).append(
                    {
                        "tool": "run_manifest",
                        "reason": "write_failed",
                        "impact": "run manifest sidecar unavailable",
                        "attempts": 1,
                    }
                )
                self.logger.event(
                    "manifest_write_failed",
                    error_type=type(exc).__name__,
                )
        if recorder and self.settings.trajectory_record_enabled:
            artifacts = {"report.md": state.final_report or ""}
            recorder.finalize(
                manifest_ref=str(manifest_path) if manifest_path else None,
                artifacts=artifacts,
            )
            recorder.write(
                self.settings.runs_root / research_id / "trajectory.json"
            )
        with correlation_context(run_id=research_id, node="workflow"):
            self.logger.event("run_finished", status=state.status)
        return state

    def load_state(self, research_id: str) -> ResearchState | None:
        snapshot = self.graph.get_state(self._config(research_id))
        if not snapshot.values or "research_state" not in snapshot.values:
            return None
        return self._state_from_graph_values(snapshot.values)

    def _build_graph(self):
        self.node_contracts = self._node_contracts()
        validate_contract_graph(self.node_contracts, self._contract_graph())
        graph = StateGraph(ResearchGraphState)
        graph.add_node("entry", self._graph_node("entry", self._entry_node))
        graph.add_node("planner", self._graph_node("planner", self._planner_node))
        graph.add_node(
            "research_prepare",
            self._graph_node("research_prepare", self._research_prepare_node),
        )
        graph.add_node(
            "research_one",
            self._graph_node("research_one", self._research_one_node),
        )
        graph.add_node(
            "research_join",
            self._graph_node("research_join", self._research_join_node),
        )
        graph.add_node(
            "extractor",
            self._graph_node("extractor", self._extractor_node),
        )
        graph.add_node("critic", self._graph_node("critic", self._critic_node))
        graph.add_node(
            "reflector",
            self._graph_node("reflector", self._reflector_node),
        )
        graph.add_node(
            "research_loop_decide",
            self._graph_node(
                "research_loop_decide",
                self._research_loop_decide_node,
            ),
        )
        graph.add_node(
            "research_refine",
            self._graph_node("research_refine", self._research_refine_node),
        )
        graph.add_node(
            "retry_prepare",
            self._graph_node("retry_prepare", self._retry_prepare_node),
        )
        graph.add_node(
            "retry_one",
            self._graph_node("retry_one", self._retry_one_node),
        )
        graph.add_node(
            "retry_join",
            self._graph_node("retry_join", self._retry_join_node),
        )
        graph.add_node(
            "reporter",
            self._graph_node("reporter", self._reporter_node),
        )
        graph.add_node(
            "evaluator",
            self._graph_node("evaluator", self._evaluator_node),
        )

        graph.add_edge(START, "entry")
        graph.add_conditional_edges("entry", self._route_entry)
        graph.add_conditional_edges("planner", self._route_after_planning)
        graph.add_conditional_edges("research_prepare", self._send_research_tasks)
        graph.add_edge("research_one", "research_join")
        graph.add_conditional_edges("research_join", self._route_after_research)
        graph.add_conditional_edges("extractor", self._route_after_extraction)
        graph.add_conditional_edges("critic", self._route_after_critic)
        graph.add_conditional_edges(
            "research_loop_decide",
            self._route_after_research_loop,
        )
        graph.add_conditional_edges(
            "reflector",
            self._route_after_reflection,
        )
        graph.add_edge("research_refine", "research_prepare")
        graph.add_conditional_edges("retry_prepare", self._send_retry_tasks)
        graph.add_edge("retry_one", "retry_join")
        graph.add_edge("retry_join", "critic")
        graph.add_conditional_edges("reporter", self._route_after_reporting)
        graph.add_edge("evaluator", END)
        return graph.compile(checkpointer=self.checkpointer)

    def _contract_graph(self) -> ContractGraph:
        return ContractGraph(
            edges=(
                ("entry", "planner"),
                ("entry", "research_prepare"),
                ("entry", "extractor"),
                ("entry", "critic"),
                ("entry", "reporter"),
                ("entry", "evaluator"),
                ("planner", "research_prepare"),
                ("research_prepare", "research_one"),
                ("research_prepare", "research_join"),
                ("research_one", "research_join"),
                ("research_join", "extractor"),
                ("extractor", "critic"),
                ("critic", "retry_prepare"),
                ("critic", "reporter"),
                ("critic", "research_loop_decide"),
                ("critic", "reflector"),
                ("research_loop_decide", "reporter"),
                ("research_loop_decide", "research_refine"),
                ("research_loop_decide", "reflector"),
                ("reflector", "reporter"),
                ("reflector", "research_refine"),
                ("research_refine", "research_prepare"),
                ("retry_prepare", "retry_one"),
                ("retry_prepare", "retry_join"),
                ("retry_one", "retry_join"),
                ("retry_join", "critic"),
                ("reporter", "evaluator"),
            ),
            injected_paths=frozenset(
                {
                    "research_state",
                    "fanout_sub_question",
                    "fanout_retry_task",
                }
            ),
        )

    def _node_contracts(self) -> dict[str, NodeContract]:
        state_field = ContractField(dict)
        optional_dict = ContractField(dict, required=False)
        identity = ContractInvariant(
            name="research_identity_preserved",
            predicate=self._research_identity_preserved,
            expectation="research_id and topic remain unchanged across the node",
        )
        return {
            "entry": NodeContract(
                name="entry",
                consumes={"research_state": state_field},
                produces=frozenset({"research_state"}),
                invariants=(identity,),
            ),
            "planner": NodeContract(
                name="planner",
                consumes={"research_state": state_field},
                produces=frozenset(
                    {
                        "research_state.plan",
                        "research_state.todo_list",
                        "research_state.pending_tasks",
                        "research_state.current_phase",
                    }
                ),
                invariants=(identity,),
            ),
            "research_prepare": NodeContract(
                name="research_prepare",
                consumes={
                    "research_state": state_field,
                    "research_state.plan": ContractField(dict),
                },
                produces=frozenset(
                    {
                        "research_state",
                        "active_sub_question_ids",
                    }
                    | (
                        {"research_state.agent_decisions"}
                        if self.settings.dynamic_capability_enabled
                        else set()
                    )
                ),
                invariants=(
                    identity,
                    *(
                        (
                            ContractInvariant(
                                name="selected_capabilities_registered",
                                predicate=(
                                    self._selected_capabilities_registered
                                ),
                                expectation=(
                                    "every selected capability resolves from "
                                    "CapabilityRegistry"
                                ),
                            ),
                        )
                        if self.settings.dynamic_capability_enabled
                        else ()
                    ),
                ),
                decision_node=self.settings.dynamic_capability_enabled,
            ),
            "research_one": NodeContract(
                name="research_one",
                consumes={
                    "research_state": state_field,
                    "fanout_sub_question": ContractField(dict),
                },
                produces=frozenset(
                    {
                        "research_sources",
                        "research_records",
                        "research_structured_evidence",
                        "research_structured_stats",
                        "research_symbol_resolutions",
                        "research_decisions",
                    }
                ),
                invariants=(identity,),
            ),
            "research_join": NodeContract(
                name="research_join",
                consumes={
                    "research_state": state_field,
                    "research_state.plan": ContractField(dict),
                    "research_sources": optional_dict,
                    "research_records": optional_dict,
                    "research_structured_evidence": optional_dict,
                    "research_structured_stats": optional_dict,
                    "research_symbol_resolutions": optional_dict,
                    "research_decisions": optional_dict,
                },
                produces=frozenset(
                    {
                        "research_state.sources",
                        "research_state.search_records",
                        "research_state.evidence_store",
                        "research_state.current_phase",
                        *(
                            {"research_state.agent_decisions"}
                            if self.settings.dynamic_capability_enabled
                            else set()
                        ),
                    }
                ),
                invariants=(identity,),
                decision_node=self.settings.dynamic_capability_enabled,
            ),
            "extractor": NodeContract(
                name="extractor",
                consumes={
                    "research_state": state_field,
                    "research_state.plan": ContractField(dict),
                    "research_state.sources": ContractField(list),
                },
                produces=frozenset(
                    {
                        "research_state.evidence_store",
                        "research_state.current_phase",
                    }
                ),
                invariants=(identity,),
            ),
            "critic": NodeContract(
                name="critic",
                consumes={
                    "research_state": state_field,
                    "research_state.plan": ContractField(dict),
                    "research_state.evidence_store": ContractField(list),
                },
                produces=frozenset(
                    {
                        "research_state.critic_report",
                        "research_state.retry_queue",
                        "research_state.current_phase",
                    }
                    | (
                        {"research_state.agent_decisions"}
                        if self.settings.numeric_check_enabled
                        else set()
                    )
                ),
                invariants=(
                    identity,
                    *(
                        (
                            ContractInvariant(
                                name="numeric_issues_complete",
                                predicate=(
                                    self._numeric_issues_complete
                                ),
                                expectation=(
                                    "every numeric_inconsistency carries "
                                    "claimed_value, calculated_value, "
                                    "formula, and evidence_ids"
                                ),
                            ),
                        )
                        if self.settings.numeric_check_enabled
                        else ()
                    ),
                ),
                decision_node=self.settings.numeric_check_enabled,
            ),
            "reflector": NodeContract(
                name="reflector",
                consumes={
                    "research_state": state_field,
                    "research_state.agent_decisions": ContractField(list),
                },
                produces=frozenset(
                    {
                        "research_state.metadata.reflection_result",
                        "research_state.agent_decisions",
                    }
                ),
                invariants=(identity,),
                decision_node=self.settings.reflection_enabled,
            ),
            "research_loop_decide": NodeContract(
                name="research_loop_decide",
                consumes={
                    "research_state": state_field,
                    "research_state.plan": ContractField(dict),
                    "research_state.evidence_store": ContractField(list),
                    "research_state.critic_report": ContractField(dict),
                },
                produces=frozenset(
                    {
                        "research_state.metadata",
                        "research_state.agent_decisions",
                    }
                ),
                invariants=(identity,),
                decision_node=True,
            ),
            "research_refine": NodeContract(
                name="research_refine",
                consumes={
                    "research_state": state_field,
                    "research_state.plan": ContractField(dict),
                },
                produces=frozenset(
                    {
                        "research_state.plan",
                        "research_state.agent_decisions",
                    }
                ),
                invariants=(identity,),
                decision_node=True,
            ),
            "retry_prepare": NodeContract(
                name="retry_prepare",
                consumes={
                    "research_state": state_field,
                    "research_state.retry_queue": ContractField(list),
                },
                produces=frozenset(
                    {
                        "research_state",
                        "active_retry_task_ids",
                    }
                ),
                invariants=(identity,),
            ),
            "retry_one": NodeContract(
                name="retry_one",
                consumes={
                    "research_state": state_field,
                    "fanout_retry_task": ContractField(dict),
                },
                produces=frozenset(
                    {
                        "retry_sources",
                        "retry_records",
                    }
                ),
                invariants=(identity,),
            ),
            "retry_join": NodeContract(
                name="retry_join",
                consumes={
                    "research_state": state_field,
                    "research_state.retry_queue": ContractField(list),
                    "retry_sources": optional_dict,
                    "retry_records": optional_dict,
                },
                produces=frozenset(
                    {
                        "research_state.evidence_store",
                        "research_state.retry_queue",
                        "research_state.current_phase",
                    }
                ),
                invariants=(identity,),
            ),
            "reporter": NodeContract(
                name="reporter",
                consumes={
                    "research_state": state_field,
                    "research_state.plan": ContractField(dict),
                    "research_state.evidence_store": ContractField(list),
                },
                produces=frozenset(
                    {
                        "research_state.final_report",
                        "research_state.draft_report",
                        "research_state.report_footnote_evidence",
                        "research_state.current_phase",
                    }
                ),
                invariants=(
                    identity,
                    ContractInvariant(
                        name="footnotes_reference_known_evidence",
                        predicate=self._footnotes_reference_known_evidence,
                        expectation=(
                            "every report footnote maps to an evidence id in "
                            "research_state.evidence_store"
                        ),
                    ),
                ),
            ),
            "evaluator": NodeContract(
                name="evaluator",
                consumes={
                    "research_state": state_field,
                    "research_state.final_report": ContractField(str),
                    "research_state.evidence_store": ContractField(list),
                    "research_state.report_footnote_evidence": ContractField(dict),
                },
                produces=frozenset(
                    {
                        "research_state.evaluation",
                        "research_state.current_phase",
                        "research_state.status",
                    }
                ),
                invariants=(identity,),
            ),
        }

    def _research_identity_preserved(
        self,
        before: dict[str, Any],
        after: dict[str, Any],
    ) -> bool:
        before_state = before.get("research_state")
        after_state = after.get("research_state")
        if not isinstance(before_state, dict) or not isinstance(after_state, dict):
            return False
        return (
            before_state.get("research_id") == after_state.get("research_id")
            and before_state.get("topic") == after_state.get("topic")
        )

    def _footnotes_reference_known_evidence(
        self,
        _before: dict[str, Any],
        after: dict[str, Any],
    ) -> bool:
        state = after.get("research_state")
        if not isinstance(state, dict):
            return False
        evidence_ids = {
            item.get("id")
            for item in state.get("evidence_store", [])
            if isinstance(item, dict)
        }
        mapping = state.get("report_footnote_evidence")
        return isinstance(mapping, dict) and set(mapping.values()).issubset(evidence_ids)

    def _numeric_issues_complete(
        self,
        _before: dict[str, Any],
        after: dict[str, Any],
    ) -> bool:
        state = after.get("research_state")
        if not isinstance(state, dict):
            return False
        report = state.get("critic_report")
        if not isinstance(report, dict):
            return False
        return all(
            issue.get("claimed_value") is not None
            and issue.get("calculated_value") is not None
            and bool(issue.get("formula"))
            and bool(issue.get("evidence_ids"))
            for issue in report.get("issues", [])
            if isinstance(issue, dict)
            and issue.get("issue_type") == "numeric_inconsistency"
        )

    def _selected_capabilities_registered(
        self,
        _before: dict[str, Any],
        after: dict[str, Any],
    ) -> bool:
        state = after.get("research_state")
        if not isinstance(state, dict):
            return False
        metadata = state.get("metadata", {})
        selections = (
            metadata.get("capability_selections", {})
            if isinstance(metadata, dict)
            else {}
        )
        if not isinstance(selections, dict) or not selections:
            return False
        registered = {
            item.name for item in self.capability_registry.query()
        }
        return all(
            isinstance(selection, dict)
            and bool(selection.get("selected_capabilities"))
            and set(
                selection.get("selected_capabilities", [])
            ).issubset(registered)
            for selection in selections.values()
        )

    def _graph_node(self, name: str, node):
        contracted = enforce_node_contract(self.node_contracts[name], node)
        return self._traced_node(name, contracted)

    def _traced_node(self, name: str, node):
        def traced(graph_state: ResearchGraphState):
            result = node(graph_state)
            recorder = active_trajectory_recorder()
            if recorder:
                recorder.record_node_transition(
                    NodeTransitionTrace(
                        node=name,
                        input_summary=_trace_graph_summary(graph_state),
                        output_summary=_trace_graph_summary(result),
                    )
                )
            return result

        return traced

    def _entry_node(self, graph_state: ResearchGraphState) -> ResearchGraphState:
        if not self.settings.skill_packs_enabled:
            return graph_state
        state = self._state_from_graph_values(graph_state)
        skill_metadata = state.metadata.get("skill_packs")
        if isinstance(skill_metadata, dict) and skill_metadata.get(
            "selection_complete"
        ):
            return graph_state
        outcome = load_skills_if_enabled(
            self.settings,
            self.skill_loader,
            state.topic,
            registry=self.capability_registry,
            state=state,
            is_applicable=finance_metric_skill_applicable,
        )
        state.metadata["skill_packs"] = {
            "selection_complete": True,
            "selected_skills": list(outcome.selected_skills),
            "registered_capabilities": list(
                outcome.registered_capabilities
            ),
        }
        result = dict(graph_state)
        result["research_state"] = self._dump_state(state)
        return result

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
        if self._branch_budget_enabled() and self.branch_budget is None:
            total_budget = (
                self.settings.research_loop_budget_ceiling
                if self.settings.research_loop_active
                else self.settings.branch_total_budget
            )
            self.branch_budget = BranchBudget(
                total_budget=total_budget,
                per_branch_cap=self.settings.branch_single_cap,
            )
            allocations = self.branch_budget.allocate(branch_ids, state)
            state.metadata["branch_budget"] = {
                "unit": "search_calls",
                "total_budget": total_budget,
                "per_branch_cap": self.settings.branch_single_cap,
                "allocations": self.branch_budget.snapshot(),
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

    def _research_one_node(self, graph_state: ResearchGraphState) -> ResearchGraphState:
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
                max_search_calls=allocation,
                priority_urls=priority_urls,
                enable_web_search=(
                    "web_search" in selected_capabilities
                ),
                enable_web_fetch=(
                    self.settings.dynamic_capability_enabled
                    and "web_fetch" in selected_capabilities
                ),
                source_decision_enabled=self.settings.dynamic_capability_enabled,
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
                max_search_calls=None,
                priority_urls=priority_urls,
                enable_web_search=(
                    "web_search" in selected_capabilities
                ),
                enable_web_fetch=(
                    self.settings.dynamic_capability_enabled
                    and "web_fetch" in selected_capabilities
                ),
                source_decision_enabled=self.settings.dynamic_capability_enabled,
            )
        else:
            if "web_search" in selected_capabilities:
                sources, records = self.researcher.research(sub_question)
                search_calls = len(records)
                branch_exhausted = False
                source_decisions = []
            else:
                sources = []
                records = []
                search_calls = 0
                branch_exhausted = False
                source_decisions = []
        structured_evidence = (
            self.researcher.structured_evidence(
                state.research_id,
                sub_question,
            )
            if "structured_data_provider" in selected_capabilities
            else []
        )
        structured_stats = (
            dict(self.researcher.last_structured_stats)
            if "structured_data_provider" in selected_capabilities
            else {
                "requests": len(
                    sub_question.structured_data_requests
                ),
                "records": 0,
                "symbol_resolution_failures": 0,
                "execution_failures": 0,
            }
        )
        symbol_resolutions = (
            list(self.researcher.last_symbol_resolutions)
            if "structured_data_provider" in selected_capabilities
            else []
        )
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
        if self._branch_budget_enabled() and self.branch_budget:
            for sub_question in state.plan.sub_questions:
                used = int(budget_usage.get(sub_question.id, 0))
                self.branch_budget.consume(sub_question.id, used, state)
            metrics = {
                sub_question.id: float(
                    len(source_batches.get(sub_question.id, []))
                    + len(structured_batches.get(sub_question.id, []))
                )
                for sub_question in state.plan.sub_questions
            }
            if not self.settings.research_loop_active:
                self.branch_budget.reallocate(
                    metrics,
                    state,
                )
            state.metadata["branch_budget"].update(
                {
                    "allocations": self.branch_budget.snapshot(),
                    "allocated_calls": {
                        branch_id: int(item["remaining"])
                        for branch_id, item in (
                            self.branch_budget.snapshot().items()
                        )
                    },
                    "metrics": metrics,
                    "branch_coverage": branch_coverage,
                    "phase": "after_join",
                    "total_used": self.branch_budget.total_used,
                }
            )
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
        recorder: TrajectoryRecorder,
    ) -> None:
        if not state.plan:
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
            )
            self.procedural_memory.write(record)
            key = {
                "question_type": record.question_type,
                "run_id": record.run_id,
                "sub_question_id": record.sub_question_id,
                "iteration": record.iteration,
            }
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
                made_by="Reflector",
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
    ) -> ResearchGraphState:
        state = self._state_from_graph_values(graph_state)
        sufficiency = evaluate_research_sufficiency(
            state,
            as_of=self.research_as_of,
            thresholds=self.sufficiency_thresholds,
        )
        state.metadata["research_loop_score"] = sufficiency.score
        if self.branch_budget:
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
                    budget_total=self.branch_budget.total_budget,
                    budget_used=self.branch_budget.total_used,
                    budget_snapshot=self.branch_budget.snapshot(),
                    sufficiency=sufficiency,
                )
                if self.settings.decision_weaving_enabled
                else None
            )
            self.branch_budget.reallocate(
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
                    "allocations": self.branch_budget.snapshot(),
                    "allocated_calls": {
                        branch_id: int(item["remaining"])
                        for branch_id, item in (
                            self.branch_budget.snapshot().items()
                        )
                    },
                    "metrics": branch_metrics,
                    "phase": "after_sufficiency",
                    "total_used": self.branch_budget.total_used,
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
                    self.branch_budget.total_budget
                    if self.branch_budget
                    else self.settings.research_loop_budget_ceiling
                ),
                budget_used=(
                    self.branch_budget.total_used
                    if self.branch_budget
                    else tracker.budget_used
                ),
                budget_snapshot=(
                    self.branch_budget.snapshot()
                    if self.branch_budget
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
                        self.branch_budget.total_budget
                        if self.branch_budget
                        else 0
                    ),
                    budget_used=(
                        self.branch_budget.total_used
                        if self.branch_budget
                        else 0
                    ),
                    budget_snapshot=(
                        self.branch_budget.snapshot()
                        if self.branch_budget
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
        state = self._state_from_graph_values(graph_state)
        task = RetryTask.model_validate(graph_state["fanout_retry_task"])
        if (
            self.settings.dynamic_capability_enabled
            and task.sub_question_id
        ):
            selections = state.metadata.get(
                "capability_selections",
                {},
            )
            selection = (
                selections.get(task.sub_question_id, {})
                if isinstance(selections, dict)
                else {}
            )
            selected = (
                selection.get("selected_capabilities", [])
                if isinstance(selection, dict)
                else []
            )
            if "web_search" not in selected:
                return {
                    "retry_sources": {task.id: []},
                    "retry_records": {
                        task.id: SearchRecord(
                            query=(
                                "[capability_not_selected] "
                                f"{task.query}"
                            ),
                            source_ids=[],
                        ).model_dump(mode="json")
                    },
                }
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
        if (
            self.settings.decision_weaving_enabled
            or self.settings.numeric_check_enabled
            or self.settings.dynamic_capability_enabled
        ):
            state.metadata["stable_reader_evidence_refs"] = True
        self._sync_tool_degradation(state)
        state.evidence_store = self._sorted_evidence(state.evidence_store)
        if self.settings.context_packer_enabled:
            self.working_memory.write(
                WorkingMemoryWrite(
                    research_id=state.research_id,
                    evidence=state.evidence_store,
                )
            )
            packed = self.working_memory.query(
                WorkingMemoryQuery(
                    research_id=state.research_id,
                    topic=state.topic,
                    budget=self.settings.reporter_context_token_budget,
                    as_of=self.settings.as_of,
                )
            )
            state.evidence_store = packed.selected
            state.metadata.setdefault("context_events", []).append(
                packed.context_event(node="reporter")
            )
        state.final_report = self.reporter.report(state)
        if self.settings.decision_weaving_enabled:
            state.final_report = append_decision_chain(
                state.final_report,
                state.agent_decisions,
            )
        if self.settings.structured_output_enabled:
            state.structured_output = self.reporter.structured_output(state)
        state.final_report = self._append_degradation_notice(state.final_report, state)
        state.final_report = self._append_research_process(
            state.final_report,
            state,
        )
        state.final_report = self._append_prior_differences(
            state.final_report,
            state,
        )
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
        recorder = active_trajectory_recorder()
        if recorder:
            recorder.trajectory.request["recorded_plan"] = (
                state.plan.model_dump(mode="json")
            )
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

    def _sync_tool_degradation(self, state: ResearchState) -> None:
        provider_events = getattr(
            self.capability_registry.resolve("web_search"),
            "degradation_events",
            [],
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

    def _append_degradation_notice(self, report: str, state: ResearchState) -> str:
        events = state.metadata.get("degradation_events", [])
        if not events:
            return report
        lines = [report.rstrip(), "", "## 数据获取降级"]
        for event in events:
            lines.append(
                "- "
                f"{event.get('tool', 'tool')} / {event.get('reason', 'unknown')}: "
                f"{event.get('impact', 'tool output unavailable')} "
                f"(attempts={int(event.get('attempts', 0))})"
            )
        return "\n".join(lines)

    def _append_research_process(
        self,
        report: str,
        state: ResearchState,
    ) -> str:
        if not self.settings.research_loop_active:
            return report
        process = state.metadata.get("research_process", [])
        if not process:
            return report
        lines = [report.rstrip(), "", "## 研究过程", ""]
        for item in process:
            iteration = int(item.get("iteration", 0))
            sufficiency = item.get("sufficiency", {})
            decision = item.get("decision", {})
            budget = item.get("budget", {})
            lines.extend(
                [
                    f"### 第 {iteration} 轮",
                    "",
                    "- 检索意图："
                    + json.dumps(
                        item.get("queries", {}),
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    (
                        "- 充分性总分："
                        f"{float(sufficiency.get('score', 0.0)):.3f}"
                    ),
                ]
            )
            for metrics in sufficiency.get("by_sub_question", []):
                lines.append(
                    "- "
                    f"{metrics.get('sub_question_id')}: "
                    f"evidence={metrics.get('evidence_count')}, "
                    f"domains={metrics.get('independent_source_domains')}, "
                    f"confidence={float(metrics.get('average_confidence', 0.0)):.3f}, "
                    f"freshest_age_days={metrics.get('freshest_evidence_age_days')}, "
                    f"critic_issues={metrics.get('unresolved_critic_issues')}, "
                    f"missing_counterargument={metrics.get('missing_counterargument')}, "
                    f"gaps={metrics.get('gaps', [])}"
                )
            lines.append(
                "- 循环决策："
                f"{decision.get('outcome')}；判据："
                f"{decision.get('criterion')}"
            )
            if budget:
                lines.append(
                    "- 预算分配："
                    + json.dumps(
                        {
                            "total_budget": budget.get("total_budget"),
                            "total_used": budget.get("total_used"),
                            "allocations": budget.get("allocations", {}),
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )
            reflection_effect = item.get("reflection_effect")
            if isinstance(reflection_effect, dict):
                signals = reflection_effect.get(
                    "deterministic_signals",
                    {},
                )
                has_signal = (
                    isinstance(signals, dict)
                    and any(bool(value) for value in signals.values())
                )
                if has_signal:
                    lines.append(
                        "- 反思如何影响重规划：仅使用确定性跨轮信号 "
                        + json.dumps(
                            signals,
                            ensure_ascii=False,
                            sort_keys=True,
                        )
                    )
                else:
                    lines.append(
                        "- 反思如何影响重规划：本轮未发现跨轮重复模式，"
                        "因此没有追加反思定向条件。"
                    )
                lines.append(
                    "- 下一轮检索意图："
                    + json.dumps(
                        reflection_effect.get(
                            "adjusted_queries",
                            {},
                        ),
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                    + "；LLM 洞察未参与，待 019。"
                )
            if item.get("stop_boundary"):
                lines.append(
                    f"- 停止说明：因 {item['stop_boundary']} 边界停止，覆盖可能不足。"
                )
            lines.append("")
        return "\n".join(lines).rstrip()

    def _append_prior_differences(
        self,
        report: str,
        state: ResearchState,
    ) -> str:
        if not self.settings.prior_memory_enabled:
            return report
        prior_metadata = state.metadata.get("prior_memory", {})
        raw_snapshot = (
            prior_metadata.get("snapshot")
            if isinstance(prior_metadata, dict)
            else None
        )
        if not isinstance(raw_snapshot, dict):
            return report
        snapshot = ResearchSnapshot.model_validate(raw_snapshot)
        rows = prior_difference_rows(state, snapshot)
        state.metadata["prior_memory"]["differences"] = rows
        lines = [
            report.rstrip(),
            "",
            "## 与上期结论的差异",
            "",
            f"对比基准：{snapshot.as_of.isoformat()}；仅比较最近一期记忆。",
        ]
        for row in rows:
            evidence_ids = ", ".join(row["evidence_ids"]) or "无"
            lines.append(
                "- "
                f"{row['status']}：{row['prior']} "
                f"{row['explanation']} 支撑 Evidence：{evidence_ids}"
            )
        return "\n".join(lines)
