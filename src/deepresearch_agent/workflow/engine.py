from __future__ import annotations

import sqlite3
import time
import traceback
from collections.abc import Sequence
from datetime import datetime
from typing import Annotated, Any, TypedDict
from urllib.parse import urlsplit

from deepresearch_agent.agents import CriticAgent, Evaluator, ExtractorAgent, PlannerAgent, ReporterAgent, ResearcherAgent
from deepresearch_agent.config_validation import validate_required_configuration
from deepresearch_agent.decisions import record_agent_decision
from deepresearch_agent.domains.protocols import DomainPack
from deepresearch_agent.domains.registry import load_domain_pack
from deepresearch_agent.llm import BudgetExceededError, LLMClient
from deepresearch_agent.memory import (
    ContextWorkingMemory,
    EpisodicMemory,
    ProceduralMemory,
)
from deepresearch_agent.observability import (
    JsonLogger,
    correlation_context,
)
from deepresearch_agent.orchestration import (
    BoundedLoop,
    DecisionGate,
    GraphRuntime,
    RunScope,
    SearchQuota,
    LoopIterationResult,
    LoopSpec,
    SufficiencyThresholds,
    validate_contract_graph,
)
from deepresearch_agent.provenance import build_run_manifest, write_run_manifest
from deepresearch_agent.reflection import Reflector
from deepresearch_agent.semantic_judge import RuntimeSemanticJudge
from deepresearch_agent.reporting import (
    GroundedFactRenderer,
    ReporterContextBuilder,
)
from deepresearch_agent.schemas import (
    AgentDecision,
    ResearchState,
    utc_now,
)
from deepresearch_agent.settings import Settings, load_settings, project_root
from deepresearch_agent.workflow.nodes.research import ResearchNodes
from deepresearch_agent.workflow.nodes.retry import RetryNodes
from deepresearch_agent.workflow.nodes.research_loop import ResearchLoopNodes
from deepresearch_agent.workflow.nodes.delivery import DeliveryNodes
from deepresearch_agent.workflow.nodes.planning import PlanningNodes
from deepresearch_agent.workflow.nodes.quality import QualityNodes
from deepresearch_agent.workflow.helpers import WorkflowHelpers
from deepresearch_agent.workflow.contracts import (
    build_workflow_contracts,
    workflow_contract_graph,
)
from deepresearch_agent.skills import (
    SkillPackLoader,
    finance_metric_skill_applicable,
    load_skills_if_enabled,
)
from deepresearch_agent.storage import SQLiteStore
from deepresearch_agent.tools import (
    CapabilityRegistry,
    DeterministicCapabilitySelector,
    SearchProvider,
    StructuredDataProvider,
    TrajectoryStructuredDataProvider,
    RunToolContext,
    ToolErrorKind,
    ToolExecutionError,
    build_capability_registry,
    build_search_provider,
    build_structured_data_provider,
)
from deepresearch_agent.tools.disclosure_source import (
    CninfoDisclosureSource,
    FixtureDisclosureSource,
)
from deepresearch_agent.tools.contract_adapter import ContractSearchProvider
from deepresearch_agent.trajectory import (
    TrajectoryRecorder,
    TrajectoryTermination,
    trajectory_recording,
)
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph


def _merge_dicts(left: dict[str, Any] | None, right: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(left or {})
    merged.update(right or {})
    return merged


def _provider_fidelity(provider: object) -> str:
    """Read the provider's explicit provenance declaration without guessing."""
    fidelity = getattr(provider, "fidelity", "unknown")
    return fidelity if fidelity in {"real", "fixture", "replay"} else "unknown"


def _research_progress_metric(state: ResearchState) -> float:
    evidence = {item.id: item for item in state.evidence_store}.values()
    components = {
        "unique_evidence": len({item.id for item in evidence}),
        "independent_domains": len({urlsplit(item.source_url).netloc for item in evidence}),
        "primary_sources": len({item.source_url for item in evidence if item.source_tier == "primary"}),
        "unresolved_issues": len(state.critic_report.issues) if state.critic_report else 0,
    }
    state.metadata["research_progress_components"] = components
    return float(
        components["unique_evidence"] + components["independent_domains"]
        + components["primary_sources"] - components["unresolved_issues"]
    )


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


class DeepResearchEngine(ResearchNodes, RetryNodes, ResearchLoopNodes, DeliveryNodes, PlanningNodes, QualityNodes, WorkflowHelpers):
    def __init__(
        self,
        settings: Settings | None = None,
        store: SQLiteStore | None = None,
        search_tool: SearchProvider | None = None,
        structured_data_provider: StructuredDataProvider | None = None,
        episodic_memory: EpisodicMemory | None = None,
        procedural_memory: ProceduralMemory | None = None,
        disclosure_source: Any | None = None,
        grounded_fact_renderer: GroundedFactRenderer | None = None,
        domain_pack: DomainPack | None = None,
    ) -> None:
        self.settings = settings or load_settings()
        self.domain_pack = domain_pack or load_domain_pack(self.settings.domain_pack)
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
        configured_disclosure_source = disclosure_source or (
            FixtureDisclosureSource()
            if self.settings.execution_mode == "deterministic"
            else CninfoDisclosureSource(
                pdf_max_pages=self.settings.pdf_max_pages,
                char_limit=self.settings.tavily_raw_content_char_limit,
            )
        )
        self.capability_registry: CapabilityRegistry = (
            build_capability_registry(
                search_provider=configured_search_tool,
                structured_data_provider=configured_structured_provider,
                disclosure_source=configured_disclosure_source,
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
        self.planner = PlannerAgent(
            llm_client=self.llm_client,
            settings=self.settings,
            domain_pack=self.domain_pack,
        )
        self.researcher = ResearcherAgent(
            search_tool=self.capability_registry.resolve("web_search"),
            structured_data_provider=self.capability_registry.resolve(
                "structured_data_provider"
            ),
            max_searches_per_run=self.settings.max_searches_per_run,
            fetch_tool=self.capability_registry.resolve("web_fetch"),
            disclosure_source=self.capability_registry.resolve(
                "disclosure_source"
            ),
            as_of=self.settings.as_of,
            domain_pack=self.domain_pack,
        )
        self.extractor = ExtractorAgent(
            llm_client=self.llm_client,
            injection_guard_enabled=self.settings.injection_guard_enabled,
            domain_pack=self.domain_pack,
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
            domain_pack=self.domain_pack,
        )
        self.reporter = ReporterAgent(
            llm_client=self.llm_client,
            grounded_fact_renderer=(
                grounded_fact_renderer or self.domain_pack.grounded_fact_renderer()
            ),
            numeric_citation_policy=self.domain_pack.numeric_citation_policy(),
        )
        semantic_judge = (
            RuntimeSemanticJudge(self.llm_client)
            if self.settings.semantic_judge_enabled and self.llm_client
            else None
        )
        self.evaluator = Evaluator(
            semantic_judge=semantic_judge,
            numeric_citation_policy=self.domain_pack.numeric_citation_policy(),
            semantic_judge_enabled=self.settings.semantic_judge_enabled,
        )
        self.reflector = Reflector()
        self.working_memory = ContextWorkingMemory()
        self.reporter_context_builder = ReporterContextBuilder(
            self.working_memory
        )
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
                progress_metric=_research_progress_metric,
                on_exhausted=self._on_research_loop_exhausted,
                budget_unit="calls",
            ),
            step=lambda _state, _context: LoopIterationResult(
                budget_consumed=0
            ),
        )
        self._checkpoint_conn = sqlite3.connect(
            self.settings.storage_path,
            check_same_thread=False,
            timeout=30,
        )
        self._checkpoint_conn.execute("PRAGMA journal_mode=WAL")
        self._checkpoint_conn.execute("PRAGMA busy_timeout=30000")
        self.checkpointer = SqliteSaver(self._checkpoint_conn)
        self.graph = self._build_graph()

    def close(self) -> None:
        """Release process resources owned by this engine deterministically."""
        self._checkpoint_conn.close()
        for capability in ("disclosure_source", "structured_data_provider"):
            close = getattr(self.capability_registry.resolve(capability), "close", None)
            if callable(close):
                close()

    def __enter__(self) -> "DeepResearchEngine":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

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
        return self._run_once(
            topic=topic,
            depth_level=depth_level,
            research_id=research_id,
            resume=resume,
            stop_after_phase=stop_after_phase,
            interrupt_before=interrupt_before,
            interrupt_after=interrupt_after,
        )

    def _run_once(
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
        run_scope = RunScope(
            tool_context=RunToolContext.for_run(
            max_external_search_requests=(
                self.settings.max_external_search_requests_per_run
            ),
            max_external_fetch_requests=(
                self.settings.max_external_fetch_requests_per_run
            ),
            max_authority_search_requests=(
                self.settings.max_authority_search_requests_per_run
            ),
            max_authority_fetch_requests=(
                self.settings.max_authority_fetch_requests_per_run
            ),
            ),
            search_quota=SearchQuota(self.researcher.max_searches_per_run),
        )
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
            state.metadata["provider_identity"] = {
                "search": type(self.search_tool).__name__,
                "structured_data": type(self.structured_data_provider).__name__,
                "disclosure": type(self.capability_registry.resolve("disclosure_source")).__name__,
                "llm": type(self.llm_client).__name__ if self.llm_client else "deterministic",
            }
            state.metadata["provider_fidelity"] = {
                "search": _provider_fidelity(self.search_tool),
                "structured_data": _provider_fidelity(self.structured_data_provider),
                "disclosure": _provider_fidelity(
                    self.capability_registry.resolve("disclosure_source")
                ),
                "llm": _provider_fidelity(self.llm_client)
                if self.llm_client
                else "fixture",
            }
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
                            "critic_enabled": (
                                self.settings.critic_enabled
                            ),
                            "extractor_enabled": (
                                self.settings.extractor_enabled
                            ),
                            "semantic_judge_enabled": (
                                self.settings.semantic_judge_enabled
                            ),
                            "context_packer_enabled": (
                                self.settings.context_packer_enabled
                            ),
                            "reporter_context_token_budget": (
                                self.settings.reporter_context_token_budget
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
                            "max_external_search_requests_per_run": (
                                self.settings.max_external_search_requests_per_run
                            ),
                            "max_external_fetch_requests_per_run": (
                                self.settings.max_external_fetch_requests_per_run
                            ),
                            "max_authority_search_requests_per_run": (
                                self.settings.max_authority_search_requests_per_run
                            ),
                            "max_authority_fetch_requests_per_run": (
                                self.settings.max_authority_fetch_requests_per_run
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
                            "procedural_memory_enabled": (
                                self.settings.procedural_memory_enabled
                            ),
                            "prior_memory_enabled": (
                                self.settings.prior_memory_enabled
                            ),
                            "prior_watch_confidence_threshold": (
                                self.settings.prior_watch_confidence_threshold
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
                        context=run_scope,
                        interrupt_before=interrupt_before,
                        interrupt_after=interrupt_after,
                    )
                state = self._state_from_graph_values(result)
                if state.status == "done" and not state.final_report:
                    state.status = "failed"
                    state.metadata["terminal_failure"] = {
                        "reason": (
                            "workflow_completed_without_final_report"
                        ),
                        "phase": state.current_phase,
                    }
                    self.graph.update_state(
                        config,
                        self._state_output(state),
                    )
                    raise RuntimeError(
                        "Workflow completed without final_report; "
                        "refusing silent success"
                    )
            except BudgetExceededError as exc:
                state = self.load_state(research_id) or state
                state.status = "budget_exceeded"
                state.metadata["terminal_failure"] = {
                    "phase": state.current_phase,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc) or type(exc).__name__,
                }
                state.metadata["llm_budget_exceeded"] = True
                state.metadata["llm_run_total_cny"] = (
                    self.llm_client.run_total_cny(research_id)
                    if self.llm_client
                    else 0.0
                )
                self._capture_external_request_budget(state, run_scope=run_scope)
                self.graph.update_state(
                    config,
                    self._state_output(state),
                )
                self._persist_run_sidecars(
                    state=state,
                    run_scope=run_scope,
                    research_id=research_id,
                    recorder=recorder,
                    manifest_started_at=manifest_started_at,
                    termination=TrajectoryTermination(
                        status="budget_exceeded",
                        phase=state.current_phase,
                        error_type=type(exc).__name__,
                        error_message=str(exc) or type(exc).__name__,
                    ),
                )
                self.logger.event("run_finished", status=state.status)
                return state
            except ToolExecutionError as exc:
                if exc.kind != ToolErrorKind.BUDGET_EXCEEDED:
                    self._persist_failed_run(
                        state=state,
                        run_scope=run_scope,
                        research_id=research_id,
                        config=config,
                        recorder=recorder,
                        manifest_started_at=manifest_started_at,
                        error=exc,
                    )
                    raise
                state = self.load_state(research_id) or state
                before = self._state_output(state)
                state.status = "budget_exceeded"
                state.metadata["terminal_failure"] = {
                    "phase": state.current_phase,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc) or type(exc).__name__,
                }
                snapshot = self._capture_external_request_budget(
                    state, run_scope=run_scope
                )
                record_agent_decision(
                    state,
                    AgentDecision(
                        decision_type="external_request_budget_rejected",
                        made_by="RunToolContext",
                        inputs=snapshot,
                        criterion="external search and fetch requests must remain within the run-wide allowance",
                        outcome=str(exc),
                        alternatives_considered=[
                            "continue after budget refusal"
                        ],
                    ),
                )
                DecisionGate.validate(
                    "external_request_budget",
                    before,
                    self._state_output(state),
                )
                try:
                    with trajectory_recording(recorder):
                        partial_report = self.reporter.report(state)
                except Exception as report_exc:
                    self.logger.event(
                        "budget_partial_report_failed",
                        error_type=type(report_exc).__name__,
                    )
                    partial_report = (
                        f"# {state.topic}\n\n"
                        "本次研究在生成部分报告前耗尽运行级预算。"
                    )
                state.final_report = (
                    f"{partial_report}\n\n"
                    "## 数据缺失与资源耗尽\n\n"
                    "本次研究在检索阶段耗尽运行级外部请求预算，后续检索、"
                    "抽取、批评与评估未能完成；因此本报告仅保留耗尽前可用的"
                    "信息，不能视为完整研究结论。\n\n"
                    f"耗尽原因：{exc}\n"
                )
                self.graph.update_state(
                    config,
                    self._state_output(state),
                )
                self._persist_run_sidecars(
                    state=state,
                    run_scope=run_scope,
                    research_id=research_id,
                    recorder=recorder,
                    manifest_started_at=manifest_started_at,
                    termination=TrajectoryTermination(
                        status="budget_exceeded",
                        phase=state.current_phase,
                        error_type=type(exc).__name__,
                        error_message=str(exc) or type(exc).__name__,
                    ),
                )
                self.logger.event("run_finished", status=state.status)
                return state
            except Exception as exc:
                self._persist_failed_run(
                    state=state,
                    run_scope=run_scope,
                    research_id=research_id,
                    config=config,
                    recorder=recorder,
                    manifest_started_at=manifest_started_at,
                    error=exc,
                )
                raise
            self._capture_external_request_budget(state, run_scope=run_scope)
            self.graph.update_state(
                config,
                self._state_output(state),
            )
            self._persist_run_sidecars(
                state=state,
                run_scope=run_scope,
                research_id=research_id,
                recorder=recorder,
                manifest_started_at=manifest_started_at,
                termination=TrajectoryTermination(
                    status="completed",
                    phase=state.current_phase,
                ),
            )
            self.logger.event("run_finished", status=state.status)
            return state

    def _capture_external_request_budget(
        self,
        state: ResearchState,
        *,
        run_scope: RunScope,
    ) -> dict[str, Any]:
        snapshot = (
            run_scope.tool_context.external_request_budget.snapshot()
            if run_scope.tool_context.external_request_budget
            else {}
        )
        state.metadata["external_request_budget"] = snapshot
        return snapshot

    def _persist_run_sidecars(
        self,
        *,
        state: ResearchState,
        run_scope: RunScope,
        research_id: str,
        recorder: TrajectoryRecorder | None,
        manifest_started_at: datetime,
        termination: TrajectoryTermination,
    ) -> None:
        self._capture_external_request_budget(state, run_scope=run_scope)
        self._capture_llm_run_cost(state)
        manifest_path = None
        if self.settings.run_manifest_enabled:
            try:
                manifest = build_run_manifest(
                    state,
                    self.settings,
                    started_at=manifest_started_at,
                    llm_config=getattr(self.llm_client, "config", None),
                )
                manifest_path = write_run_manifest(
                    manifest,
                    self.settings.runs_root,
                )
            except Exception as exc:
                state.metadata.setdefault(
                    "degradation_events",
                    [],
                ).append(
                    {
                        "tool": "run_manifest",
                        "reason": "write_failed",
                        "impact": (
                            "run manifest sidecar unavailable"
                        ),
                        "attempts": 1,
                    }
                )
                self.logger.event(
                    "manifest_write_failed",
                    error_type=type(exc).__name__,
                )
        if recorder and self.settings.trajectory_record_enabled:
            artifacts = (
                {"report.md": state.final_report or ""}
                if (
                    termination.status
                    in {"completed", "budget_exceeded"}
                    or state.final_report is not None
                )
                else {}
            )
            recorder.finalize(
                manifest_ref=(
                    str(manifest_path) if manifest_path else None
                ),
                artifacts=artifacts,
                termination=termination,
            )
            recorder.write(
                self.settings.runs_root
                / research_id
                / "trajectory.json"
            )

    def _capture_llm_run_cost(
        self,
        state: ResearchState,
    ) -> float | None:
        total_method = getattr(
            self.llm_client,
            "run_total_cny",
            None,
        )
        if not callable(total_method):
            return None
        try:
            total = round(
                float(total_method(state.research_id)),
                8,
            )
        except (OSError, TypeError, ValueError):
            return None
        state.metadata["llm_run_total_cny"] = total
        return total

    def _persist_failed_run(
        self,
        *,
        state: ResearchState,
        run_scope: RunScope,
        research_id: str,
        config: dict[str, Any],
        recorder: TrajectoryRecorder | None,
        manifest_started_at: datetime,
        error: Exception,
    ) -> None:
        state = self.load_state(research_id) or state
        state.status = "failed"
        terminal = state.metadata.get("terminal_failure", {})
        if not isinstance(terminal, dict):
            terminal = {}
        state.metadata["terminal_failure"] = {
            **terminal,
            "phase": state.current_phase,
            "error_type": type(error).__name__,
            "error_message": str(error) or type(error).__name__,
        }
        self._capture_external_request_budget(state, run_scope=run_scope)
        try:
            self.graph.update_state(
                config,
                self._state_output(state),
            )
        except Exception as checkpoint_exc:
            self.logger.event(
                "terminal_checkpoint_write_failed",
                error_type=type(checkpoint_exc).__name__,
            )
        self.logger.event(
            "run_failed",
            error_type=type(error).__name__,
            error=str(error),
            traceback=traceback.format_exc(),
        )
        try:
            self._persist_run_sidecars(
                state=state,
                run_scope=run_scope,
                research_id=research_id,
                recorder=recorder,
                manifest_started_at=manifest_started_at,
                termination=TrajectoryTermination(
                    status="failed",
                    phase=state.current_phase,
                    error_type=type(error).__name__,
                    error_message=(
                        str(error) or type(error).__name__
                    ),
                ),
            )
        except Exception as sidecar_exc:
            self.logger.event(
                "terminal_sidecar_write_failed",
                error_type=type(sidecar_exc).__name__,
            )

    def load_state(self, research_id: str) -> ResearchState | None:
        snapshot = self.graph.get_state(self._config(research_id))
        if not snapshot.values or "research_state" not in snapshot.values:
            return None
        return self._state_from_graph_values(snapshot.values)

    def _build_graph(self):
        self.node_contracts = build_workflow_contracts(
            self.settings,
            self.capability_registry,
        )
        validate_contract_graph(self.node_contracts, workflow_contract_graph())
        graph_runtime = GraphRuntime(self.node_contracts, self.logger)
        graph = StateGraph(ResearchGraphState, context_schema=RunScope)
        graph.add_node("entry", graph_runtime.wrap_node("entry", self._entry_node))
        graph.add_node("planner", graph_runtime.wrap_node("planner", self._planner_node))
        graph.add_node(
            "research_prepare",
            graph_runtime.wrap_node("research_prepare", self._research_prepare_node),
        )
        graph.add_node(
            "research_one",
            graph_runtime.wrap_node("research_one", self._research_one_node),
        )
        graph.add_node(
            "research_join",
            graph_runtime.wrap_node("research_join", self._research_join_node),
        )
        graph.add_node(
            "extractor",
            graph_runtime.wrap_node("extractor", self._extractor_node),
        )
        graph.add_node("critic", graph_runtime.wrap_node("critic", self._critic_node))
        graph.add_node(
            "reflector",
            graph_runtime.wrap_node("reflector", self._reflector_node),
        )
        graph.add_node(
            "research_loop_decide",
            graph_runtime.wrap_node(
                "research_loop_decide",
                self._research_loop_decide_node,
            ),
        )
        graph.add_node(
            "research_refine",
            graph_runtime.wrap_node("research_refine", self._research_refine_node),
        )
        graph.add_node(
            "retry_prepare",
            graph_runtime.wrap_node("retry_prepare", self._retry_prepare_node),
        )
        graph.add_node(
            "retry_one",
            graph_runtime.wrap_node("retry_one", self._retry_one_node),
        )
        graph.add_node(
            "retry_join",
            graph_runtime.wrap_node("retry_join", self._retry_join_node),
        )
        graph.add_node(
            "reporter",
            graph_runtime.wrap_node("reporter", self._reporter_node),
        )
        graph.add_node(
            "evaluator",
            graph_runtime.wrap_node("evaluator", self._evaluator_node),
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
