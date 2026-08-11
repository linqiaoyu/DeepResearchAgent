from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Sequence
from dataclasses import asdict
from threading import RLock
from typing import Any
from urllib.parse import urlsplit

from deepresearch_agent.agents import CriticAgent, Evaluator, ExtractorAgent, PlannerAgent, ReporterAgent, ResearcherAgent
from deepresearch_agent.config_validation import (
    validate_required_configuration,
    validate_security_invariants,
)
from deepresearch_agent.decisions import record_agent_decision
from deepresearch_agent.domains.protocols import DomainPack
from deepresearch_agent.domains.registry import load_domain_pack
from deepresearch_agent.llm import BudgetExceededError, LLMClient
from deepresearch_agent.memory import (
    ContextWorkingMemory,
    EpisodicMemory,
    ProceduralMemory,
    SemanticMemory,
)
from deepresearch_agent.observability import (
    JsonLogger,
    correlation_context,
)
from deepresearch_agent.observability.run_composition import (
    record_run_composition,
)
from deepresearch_agent.orchestration import (
    BoundedLoop,
    DecisionGate,
    RunScope,
    SearchQuota,
    LoopIterationResult,
    LoopSpec,
    SufficiencyThresholds,
)
from deepresearch_agent.reflection import ReflectionExecutionLimits, Reflector
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
from deepresearch_agent.security import ContentIngressGuard
from deepresearch_agent.settings import Settings, load_settings, project_root
from deepresearch_agent.workflow.nodes.research import (
    ResearchNodes,
    ResearchOneDependencies,
    ResearchOneNode,
)
from deepresearch_agent.workflow.nodes.retry import RetryNodes
from deepresearch_agent.workflow.nodes.research_loop import ResearchLoopNodes
from deepresearch_agent.workflow.nodes.delivery import DeliveryNodes
from deepresearch_agent.workflow.nodes.planning import PlanningNodes
from deepresearch_agent.workflow.nodes.quality import QualityNodes
from deepresearch_agent.workflow.helpers import WorkflowHelpers
from deepresearch_agent.workflow.graph_assembly import GraphAssembly
from deepresearch_agent.workflow.capability_setup import build_engine_capability_registry
from deepresearch_agent.workflow.run_persistence import RunPersistence
from deepresearch_agent.workflow.state import ResearchGraphState
from deepresearch_agent.skills import (
    SkillPackLoader,
)
from deepresearch_agent.storage import StorageProtocol, build_store
from deepresearch_agent.storage.sqlite_store import SQLITE_INITIALIZATION_LOCK
from deepresearch_agent.tools import (
    CapabilityRegistry,
    DeterministicCapabilitySelector,
    LLMCapabilitySelector,
    SearchProvider,
    StructuredDataProvider,
    RunToolContext,
    ToolErrorKind,
    ToolExecutionError,
)
from deepresearch_agent.trajectory import (
    TrajectoryRecorder,
    TrajectoryTermination,
    trajectory_recording,
)
from langgraph.checkpoint.sqlite import SqliteSaver


def _provider_fidelity(provider: object) -> str:
    """Read the provider's explicit provenance declaration without guessing."""
    fidelity = getattr(provider, "fidelity", "unknown")
    # `mixed` is what a routed provider declares when its members disagree.
    return (
        fidelity
        if fidelity in {"real", "fixture", "replay", "mixed"}
        else "unknown"
    )


def _provider_identity(provider: object) -> str:
    """Record the concrete provider when an observational wrapper is present."""

    identity = getattr(provider, "provider_identity", None)
    return identity if isinstance(identity, str) and identity else type(provider).__name__


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


_STRATEGY_NON_BOOLEAN_FIELDS = frozenset(
    {
        "max_critic_iter",
        "reporter_context_token_budget",
        "max_external_search_requests_per_run",
        "max_external_fetch_requests_per_run",
        "max_authority_search_requests_per_run",
        "max_authority_fetch_requests_per_run",
        "branch_total_budget",
        "branch_single_cap",
        "research_loop_max_iterations",
        "research_loop_budget_ceiling",
        "research_loop_no_progress_window",
        "research_min_evidence_count",
        "research_min_independent_domains",
        "research_min_average_confidence",
        "research_max_freshness_age_days",
        "research_max_unresolved_critic_issues",
        "decision_weaving_budget_remaining_ratio",
        "decision_weaving_verify_min_allocation",
        "numeric_check_relative_tolerance",
        "numeric_check_absolute_tolerance",
        "dynamic_capability_rules_json",
        "prior_watch_confidence_threshold",
        "reflection_max_invocations",
        "reflection_max_prompt_tokens",
        "reflection_max_completion_tokens",
        "reflection_budget_cny",
        "retrieval_top_k",
        "rerank_top_n",
    }
)


def _strategy_config(settings: Settings, *, rag_index_version: str | None) -> dict[str, object]:
    """Serialize replay-relevant settings without hand-maintained boolean drift."""

    values = asdict(settings)
    strategy = {
        name: value
        for name, value in values.items()
        if isinstance(value, bool) or name in _STRATEGY_NON_BOOLEAN_FIELDS
    }
    strategy["rag_index_version"] = rag_index_version
    return strategy


def _build_engine_llm_client(settings: Settings, logger: JsonLogger) -> LLMClient:
    """Use the configured ledger as both run and budget-accounting authority."""

    return LLMClient(
        ledger_path=settings.llm_ledger_path,
        global_ledger_path=settings.llm_ledger_path,
        budget_cny=settings.llm_budget_cny,
        logger=logger,
        fail_on_retry_exhaustion=True,
    )


class DeepResearchEngine(ResearchNodes, RetryNodes, ResearchLoopNodes, DeliveryNodes, PlanningNodes, QualityNodes, RunPersistence, WorkflowHelpers, GraphAssembly):
    def __init__(
        self,
        settings: Settings | None = None,
        store: StorageProtocol | None = None,
        search_tool: SearchProvider | None = None,
        structured_data_provider: StructuredDataProvider | None = None,
        rag_search: Any | None = None,
        episodic_memory: EpisodicMemory | None = None,
        procedural_memory: ProceduralMemory | None = None,
        semantic_memory: SemanticMemory | None = None,
        disclosure_source: Any | None = None,
        grounded_fact_renderer: GroundedFactRenderer | None = None,
        domain_pack: DomainPack | None = None,
    ) -> None:
        self.settings = settings or load_settings()
        self.domain_pack = domain_pack or load_domain_pack(self.settings.domain_pack)
        # This is a security/content invariant, not a fail-fast convenience.
        validate_security_invariants(self.settings)
        if self.settings.config_fail_fast_enabled:
            validate_required_configuration(self.settings)
        self.logger = JsonLogger(enabled=self.settings.structured_logging_enabled)
        self.content_guard = ContentIngressGuard(
            enabled=self.settings.injection_guard_enabled
        )
        self.store = store or build_store(self.settings)
        self.capability_registry: CapabilityRegistry = build_engine_capability_registry(
            settings=self.settings,
            domain_pack=self.domain_pack,
            logger=self.logger,
            search_tool=search_tool,
            structured_data_provider=structured_data_provider,
            disclosure_source=disclosure_source,
            rag_search=rag_search,
        )
        self.mcp_clients: list[Any] = []
        self.mcp_registration: dict[str, Any] = self._register_mcp_servers()
        self.skill_loader = SkillPackLoader(
            project_root() / "skills",
            content_guard=self.content_guard,
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
            _build_engine_llm_client(self.settings, self.logger)
            if self.settings.execution_mode == "llm"
            else None
        )
        if self.settings.llm_tool_selection_enabled:
            if self.llm_client is None:
                raise ValueError("LLM_TOOL_SELECTION_ENABLED requires DEEPRESEARCH_MODE=llm")
            self.capability_selector = LLMCapabilitySelector(
                self.capability_registry, self.llm_client
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
            rag_search=(
                self.capability_registry.resolve("rag_search")
                if self.settings.rag_enabled
                else None
            ),
            as_of=self.settings.as_of,
            domain_pack=self.domain_pack,
        )
        self.research_one_node = ResearchOneNode(
            ResearchOneDependencies(
                settings=self.settings,
                capability_selector=self.capability_selector,
                researcher=self.researcher,
                state_loader=self._state_from_graph_values,
                branch_budget_enabled=self._branch_budget_enabled,
            )
        )
        self.extractor = ExtractorAgent(
            llm_client=self.llm_client,
            injection_guard_enabled=self.settings.injection_guard_enabled,
            content_guard=self.content_guard,
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
            domain_pack=self.domain_pack,
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
            domain_pack=self.domain_pack,
        )
        self.reflector = Reflector(
            limits=ReflectionExecutionLimits(
                max_invocations=self.settings.reflection_max_invocations,
                max_prompt_tokens=self.settings.reflection_max_prompt_tokens,
                max_completion_tokens=(
                    self.settings.reflection_max_completion_tokens
                ),
                max_cost_cny=self.settings.reflection_budget_cny,
            )
        )
        self.working_memory = ContextWorkingMemory()
        self.reporter_context_builder = ReporterContextBuilder(
            self.working_memory
        )
        # R122: the memories declare `cross_run` and were in-process dicts, so
        # every run started empty and both memory flags read nothing. Handing
        # them the run's own store makes the declared lifetime true; an
        # explicitly injected memory is left exactly as the caller built it.
        self.episodic_memory = episodic_memory or EpisodicMemory(store=self.store)
        self.procedural_memory = procedural_memory or ProceduralMemory(store=self.store)
        self.semantic_memory = semantic_memory or SemanticMemory(store=self.store)
        self.research_as_of = self.settings.as_of or self.critic.today
        self._graph_lock = RLock()
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
        self._checkpoint_conn: Any
        if self.settings.storage_backend == "postgres":
            self._checkpoint_conn, self.checkpointer = self._postgres_checkpointer()
        else:
            with SQLITE_INITIALIZATION_LOCK:
                self._checkpoint_conn = sqlite3.connect(
                    self.settings.storage_path,
                    check_same_thread=False,
                    timeout=30,
                    isolation_level="IMMEDIATE",
                )
                # Busy timeout first: `journal_mode=WAL` can itself block.
                self._checkpoint_conn.execute("PRAGMA busy_timeout=30000")
                self._checkpoint_conn.execute("PRAGMA journal_mode=WAL")
            self.checkpointer = SqliteSaver(self._checkpoint_conn)
        self.graph = self._build_graph()

    def _postgres_checkpointer(self) -> tuple[Any, Any]:
        """Create the optional LangGraph checkpointer only for the PG profile."""

        if not self.settings.postgres_dsn:
            raise ValueError("DEEPRESEARCH_POSTGRES_DSN is required for Postgres checkpointing")
        from langgraph.checkpoint.postgres import PostgresSaver
        from psycopg import connect
        from psycopg.rows import dict_row

        connection = connect(
            self.settings.postgres_dsn,
            autocommit=True,
            row_factory=dict_row,
        )
        checkpointer = PostgresSaver(connection)
        checkpointer.setup()
        return connection, checkpointer

    def close(self) -> None:
        """Release process resources owned by this engine deterministically."""
        self._checkpoint_conn.close()
        for client in self.mcp_clients:
            client.close()
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
                "structured_data": _provider_identity(self.structured_data_provider),
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
            rag_search = self.researcher.rag_search
            if rag_search is not None:
                if isinstance(getattr(rag_search, "index_version", None), str):
                    state.metadata["retrieval_index_version"] = rag_search.index_version
                state.metadata["provider_identity"]["rag_search"] = type(rag_search).__name__
                state.metadata["provider_fidelity"]["rag_search"] = _provider_fidelity(rag_search)
            # R111: nine declared capabilities are decided here, when the run is
            # assembled, and have no unit of work to count later. Without this
            # they left no per-run evidence at all, so an archived run could not
            # say whether the tool contract or rerank had been active.
            record_run_composition(state, self.settings)
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
                        "strategy_config": _strategy_config(
                            self.settings,
                            rag_index_version=(
                                self.researcher.rag_search.index_version
                                if isinstance(getattr(self.researcher.rag_search, "index_version", None), str)
                                else None
                            ),
                        ),
                    },
                )
                if (
                    self.settings.trajectory_record_enabled
                    or self.settings.reflection_enabled
                )
                else None
            )
            try:
                with self._graph_lock:
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
                with self._graph_lock:
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
                with self._graph_lock:
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
            with self._graph_lock:
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

    def _register_mcp_servers(self) -> dict[str, Any]:
        """Discover configured external MCP servers into the capability registry.

        R123: `mcp/server.py` exposes this agent as MCP tools and works.
        `mcp/client.py` -- including `discover_and_register`, which puts a
        remote tool behind the same `ToolSpec`, budget and executor as every
        local one -- was imported by nothing outside its own package, so the
        agent could not consume an external tool and its capability set was the
        five hardcoded entries.

        A server is an outbound dependency: unreachable is a degradation the run
        records and continues past, never an exception that ends it.
        """

        summary: dict[str, Any] = {
            "enabled": self.settings.mcp_client_enabled,
            "configured": 0,
            "connected": [],
            "failed": [],
            "registered_capabilities": [],
        }
        if not self.settings.mcp_client_enabled:
            return summary
        try:
            configured = json.loads(self.settings.mcp_server_commands or "[]")
        except json.JSONDecodeError as exc:
            summary["failed"].append({"server": "<config>", "error": str(exc)})
            self.logger.event("mcp_config_invalid", error_type="JSONDecodeError")
            return summary
        summary["configured"] = len(configured)
        from deepresearch_agent.mcp import MCPStdioClient

        for entry in configured:
            name = str(entry.get("name", "")) or "unnamed"
            command = [str(part) for part in entry.get("command", [])]
            if not command:
                summary["failed"].append({"server": name, "error": "empty command"})
                continue
            before = {item.name for item in self.capability_registry.query()}
            client = None
            try:
                client = MCPStdioClient(
                    command,
                    server_name=name,
                    request_timeout_s=float(entry.get("timeout_s", 10.0)),
                    environ=entry.get("environ"),
                    content_guard=self.content_guard,
                )
                client.discover_and_register(
                    self.capability_registry,
                    ResearchState(topic=f"mcp discovery: {name}"),
                    trusted_server=bool(entry.get("trusted", False)),
                )
            except Exception as exc:
                if client is not None:
                    client.close()
                summary["failed"].append(
                    {"server": name, "error": type(exc).__name__}
                )
                self.logger.event(
                    "mcp_server_unavailable",
                    server=name,
                    error_type=type(exc).__name__,
                )
                continue
            self.mcp_clients.append(client)
            summary["connected"].append(name)
            summary["registered_capabilities"].extend(
                sorted({item.name for item in self.capability_registry.query()} - before)
            )
        return summary
