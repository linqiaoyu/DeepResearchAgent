from __future__ import annotations

import hashlib
import importlib.metadata
import json
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from deepresearch_agent.llm_config import DEFAULT_LLM_CONFIG, LLMConfig
from deepresearch_agent.schemas import AgentDecision, ResearchState, StrictModel, utc_now
from deepresearch_agent.security import redact
from deepresearch_agent.settings import Settings, project_root


class RunManifest(StrictModel):
    run_id: str
    started_at: datetime
    ended_at: datetime
    model_strings: dict[str, str]
    prompt_hashes: dict[str, str]
    retrieval_index_version: str | None = None
    retrieval_corpus_as_of: date | None = None
    evaluation_as_of: date | None = None
    config_hash: str
    dependency_versions: dict[str, str]
    domain: str
    mode: str
    flags: dict[str, bool]
    token_total: int = Field(ge=0)
    cost_cny_total: float | None = Field(default=None, ge=0)
    provider_identity: dict[str, str] = Field(default_factory=dict)
    realness: Literal["real", "mixed", "fixture", "replay", "unknown"] = "unknown"
    provider_usage: dict[str, int] = Field(default_factory=dict)
    actual_provider_fidelity: dict[str, str] = Field(default_factory=dict)
    actual_realness: Literal["real", "mixed", "fixture", "replay", "unknown"] = "unknown"
    structured_data_stats: dict[str, dict[str, Any]] = Field(default_factory=dict)
    degradation_events: list[dict[str, Any]] = Field(default_factory=list)
    context_events: list[dict[str, Any]] = Field(default_factory=list)
    tool_error_summary: dict[str, int] = Field(default_factory=dict)
    decision_summary: list[AgentDecision] = Field(default_factory=list)


class ManifestComparison(StrictModel):
    comparable: bool
    # Backward-compatible alias for callers that consumed the old flat result.
    # It contains only differences that make the runs incomparable.
    differences: dict[str, dict[str, Any]] = Field(default_factory=dict)
    incomparable_reasons: dict[str, dict[str, Any]] = Field(default_factory=dict)
    additive_differences: dict[str, dict[str, Any]] = Field(default_factory=dict)
    informational_differences: dict[str, dict[str, Any]] = Field(default_factory=dict)
    conclusion: str


COMPARABILITY_FIELDS = (
    "model_strings",
    "prompt_hashes",
    "retrieval_index_version",
    "retrieval_corpus_as_of",
    "evaluation_as_of",
    "dependency_versions",
    "domain",
    "mode",
    "config_hash",
)

# Classification evidence is the 011 product-level flag-impact replay under
# `_collab/011_baseline-and-activation/flag_impact/`, not an implementation
# claim. Context packing changed evidence and reports; injection guarding was
# inert on the held-in fixtures but can alter confidence, Critic routing, and
# content when a pattern matches.
FlagClassification = Literal[
    "content_affecting",
    "additive_content",
    "operational",
]
FLAG_CLASSIFICATIONS: dict[str, FlagClassification] = {
    "CONTEXT_PACKER_ENABLED": "content_affecting",
    "INJECTION_GUARD_ENABLED": "content_affecting",
    # 013 proved additive behavior only in deterministic mode: enabling this
    # flag added a structured object without changing the existing report,
    # claims, Evidence, Critic routing, metrics, or node summaries. Whether an
    # LLM Reporter generating both objects changes prose remains a 014
    # validation item and is not claimed here.
    "STRUCTURED_OUTPUT_ENABLED": "additive_content",
    # 011 replay showed no report/claim/evidence/metric changes for these
    # flags. RUN_MANIFEST changed only its sidecar; logging changed stdout;
    # fail-fast is startup validation; tool contracts were inert on fixture
    # happy paths. They remain operational for content comparability.
    "RUN_MANIFEST_ENABLED": "operational",
    "STRUCTURED_LOGGING_ENABLED": "operational",
    "CONFIG_FAIL_FAST_ENABLED": "operational",
    "TOOL_CONTRACT_ENABLED": "operational",
    # 012 characterization confirmed that API-level section publication
    # reassembles to the byte-identical final report. It changes polling
    # sidecars only, so it is operational rather than content-affecting.
    "PROGRESSIVE_DELIVERY_ENABLED": "operational",
    # Recording writes a redacted sidecar and does not alter report content.
    "TRAJECTORY_RECORD_ENABLED": "operational",
    "BRANCH_BUDGET_ENABLED": "content_affecting",
    "RESEARCH_LOOP_ENABLED": "content_affecting",
    "PRIOR_MEMORY_ENABLED": "content_affecting",
    "DECISION_WEAVING_ENABLED": "content_affecting",
    "NUMERIC_CHECK_ENABLED": "content_affecting",
    "DYNAMIC_CAPABILITY_ENABLED": "content_affecting",
    "LLM_TOOL_SELECTION_ENABLED": "content_affecting",
    "REFLECTION_ENABLED": "content_affecting",
    "CRITIC_ENABLED": "content_affecting",
    "EXTRACTOR_ENABLED": "content_affecting",
    "PROCEDURAL_MEMORY_ENABLED": "content_affecting",
    "SKILL_PACKS_ENABLED": "content_affecting",
    "RAG_ENABLED": "content_affecting",
    "RERANK_ENABLED": "content_affecting",
    "RERANK_FAIL_OPEN": "content_affecting",
    # The judge changes existing evaluation fields, even though it is barred
    # from changing report content or mechanical numeric correctness.
    "SEMANTIC_JUDGE_ENABLED": "content_affecting",
}


def compare_manifests(left: RunManifest, right: RunManifest) -> ManifestComparison:
    """Prevent false improvements caused by changing the judge or run conditions.

    The project previously observed an apparent quality improvement after a
    judge change. This comparison turns that manual lesson into a hard,
    machine-readable comparability decision.
    """

    incomparable: dict[str, dict[str, Any]] = {}
    additive: dict[str, dict[str, Any]] = {}
    informational: dict[str, dict[str, Any]] = {}
    for field_name in COMPARABILITY_FIELDS:
        left_value = getattr(left, field_name)
        right_value = getattr(right, field_name)
        if left_value != right_value:
            incomparable[field_name] = {
                "left": _json_value(left_value),
                "right": _json_value(right_value),
            }
    for flag_name in sorted(set(left.flags) | set(right.flags)):
        left_value = left.flags.get(flag_name)
        right_value = right.flags.get(flag_name)
        if left_value == right_value:
            continue
        difference = {"left": left_value, "right": right_value}
        field_name = f"flags.{flag_name}"
        category = FLAG_CLASSIFICATIONS.get(flag_name, "content_affecting")
        if category == "operational":
            informational[field_name] = difference
        elif category == "additive_content":
            additive[field_name] = difference
        else:
            incomparable[field_name] = difference
    comparable = not incomparable
    conclusion = (
        "comparable: only additive content, operational, or no differences detected"
        if comparable
        else "not comparable: content or run-identity differences detected"
    )
    return ManifestComparison(
        comparable=comparable,
        differences=incomparable,
        incomparable_reasons=incomparable,
        additive_differences=additive,
        informational_differences=informational,
        conclusion=conclusion,
    )


def format_manifest_comparison(comparison: ManifestComparison) -> dict[str, Any]:
    """Return the CLI's four-section, human-scannable result."""

    return {
        "incomparable_reasons": comparison.incomparable_reasons,
        "additive_differences": comparison.additive_differences,
        "informational_differences": comparison.informational_differences,
        "conclusion": {
            "comparable": comparison.comparable,
            "summary": comparison.conclusion,
        },
    }


def build_run_manifest(
    state: ResearchState,
    settings: Settings,
    *,
    started_at: datetime,
    ended_at: datetime | None = None,
    domain: str = "finance",
    llm_config: LLMConfig | None = None,
) -> RunManifest:
    if settings.execution_mode == "llm" and llm_config is None:
        raise ValueError(
            "llm_config is required when building a manifest for an LLM run"
        )
    configured_models = llm_config or DEFAULT_LLM_CONFIG
    root = project_root()
    metadata = state.metadata
    degradation_events = list(metadata.get("degradation_events", []))
    context_events = list(metadata.get("context_events", []))
    tool_errors = dict(metadata.get("tool_error_summary", {}))
    return RunManifest(
        run_id=state.research_id,
        started_at=started_at,
        ended_at=ended_at or utc_now(),
        model_strings={
            role: config.model
            for role, config in configured_models.roles.items()
            if role != "capability_selector" or settings.llm_tool_selection_enabled
        },
        prompt_hashes=_prompt_hashes(
            root / "prompts",
            include_semantic_judge=settings.semantic_judge_enabled,
        ),
        retrieval_index_version=_optional_string(metadata.get("retrieval_index_version")),
        retrieval_corpus_as_of=_optional_date(metadata.get("retrieval_corpus_as_of"))
        or settings.as_of,
        evaluation_as_of=_optional_date(metadata.get("evaluation_as_of")) or settings.as_of,
        config_hash=_config_hash(settings),
        dependency_versions=_dependency_versions(),
        domain=domain,
        mode=settings.execution_mode,
        flags=settings_flag_snapshot(settings),
        token_total=state.token_used,
        cost_cny_total=_cost_cny_total(state),
        provider_identity=dict(metadata.get("provider_identity", {})),
        realness=_realness(metadata.get("provider_fidelity", {})),
        provider_usage=_provider_usage(state),
        actual_provider_fidelity=_actual_provider_fidelity(state),
        actual_realness=_actual_realness(state),
        structured_data_stats=_structured_data_stats(state),
        degradation_events=degradation_events,
        context_events=context_events,
        tool_error_summary={str(key): int(value) for key, value in tool_errors.items()},
        decision_summary=list(state.agent_decisions),
    )


def _cost_cny_total(state: ResearchState) -> float | None:
    usage = state.metadata.get("llm_usage")
    if isinstance(usage, dict):
        value = usage.get("total_cost_cny")
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and value >= 0
        ):
            return float(value)
    run_total = state.metadata.get("llm_run_total_cny")
    if (
        isinstance(run_total, (int, float))
        and not isinstance(run_total, bool)
        and run_total >= 0
    ):
        return float(run_total)
    return None


def _realness(
    fidelity: object,
) -> Literal["real", "mixed", "fixture", "replay", "unknown"]:
    """Aggregate explicit provider declarations; absence is never evidence of reality."""
    if not isinstance(fidelity, dict) or not fidelity:
        return "unknown"
    values = list(fidelity.values())
    allowed = {"real", "fixture", "replay"}
    if any(value not in allowed for value in values):
        return "unknown"
    unique = set(values)
    if len(unique) == 1:
        return unique.pop()
    return "mixed"


def _provider_usage(state: ResearchState) -> dict[str, int]:
    """Count provider calls evidenced by the completed run, not configuration."""
    search = 0
    disclosure = 0
    rag_search = 0
    for record in state.search_records:
        query = record.query
        if query.startswith("[disclosure]"):
            disclosure += 1
        elif query.startswith("[rag_search]"):
            rag_search += 1
        elif query.startswith(("[web_fetch]", "[priority_url]", "[fetch_budget_exceeded]", "[external_fetch_budget_exceeded]")):
            continue
        elif not query.startswith("[branch_budget_exceeded]") and not query.startswith(
            "[search_limit_exceeded]"
        ) and not query.startswith("[external_search_budget_exceeded]"):
            search += 1
    structured = sum(
        int(stats.get("records", 0))
        for stats in _structured_data_stats(state).values()
        if isinstance(stats, dict)
    )
    llm_usage = state.metadata.get("llm_usage")
    llm = 1 if isinstance(llm_usage, dict) and llm_usage.get("by_role") else 0
    return {
        "search": search,
        "structured_data": structured,
        "disclosure": disclosure,
        "rag_search": rag_search,
        "llm": llm,
    }


def _structured_data_stats(state: ResearchState) -> dict[str, dict[str, Any]]:
    raw_stats = state.metadata.get("structured_data_stats")
    if not isinstance(raw_stats, dict):
        return {}
    return {
        str(sub_question_id): dict(stats)
        for sub_question_id, stats in raw_stats.items()
        if isinstance(stats, dict)
    }


def _actual_provider_fidelity(state: ResearchState) -> dict[str, str]:
    configured = state.metadata.get("provider_fidelity", {})
    usage = _provider_usage(state)
    return {
        provider: str(configured.get(provider, "unknown")) if count else "unused"
        for provider, count in usage.items()
    }


def _actual_realness(
    state: ResearchState,
) -> Literal["real", "mixed", "fixture", "replay", "unknown"]:
    actual = _actual_provider_fidelity(state)
    if not actual or any(value == "unused" for value in actual.values()):
        return "mixed" if any(value != "unused" for value in actual.values()) else "unknown"
    return _realness(actual)


def settings_flag_snapshot(
    settings: Settings,
    *,
    include_disabled_experimental: bool = False,
) -> dict[str, bool]:
    flags = {
        "TOOL_CONTRACT_ENABLED": settings.tool_contract_enabled,
        "INJECTION_GUARD_ENABLED": settings.injection_guard_enabled,
        "RUN_MANIFEST_ENABLED": settings.run_manifest_enabled,
        "CONTEXT_PACKER_ENABLED": settings.context_packer_enabled,
        "STRUCTURED_LOGGING_ENABLED": settings.structured_logging_enabled,
        "CONFIG_FAIL_FAST_ENABLED": settings.config_fail_fast_enabled,
        "CRITIC_ENABLED": settings.critic_enabled,
        "EXTRACTOR_ENABLED": settings.extractor_enabled,
        "PROCEDURAL_MEMORY_ENABLED": (
            settings.procedural_memory_enabled
        ),
    }
    if settings.structured_output_enabled or include_disabled_experimental:
        flags["STRUCTURED_OUTPUT_ENABLED"] = settings.structured_output_enabled
    if settings.progressive_delivery_enabled or include_disabled_experimental:
        flags["PROGRESSIVE_DELIVERY_ENABLED"] = (
            settings.progressive_delivery_enabled
        )
    if settings.trajectory_record_enabled or include_disabled_experimental:
        flags["TRAJECTORY_RECORD_ENABLED"] = settings.trajectory_record_enabled
    if settings.branch_budget_enabled or include_disabled_experimental:
        flags["BRANCH_BUDGET_ENABLED"] = settings.branch_budget_enabled
    if settings.research_loop_active or include_disabled_experimental:
        flags["RESEARCH_LOOP_ENABLED"] = settings.research_loop_active
    if settings.prior_memory_enabled or include_disabled_experimental:
        flags["PRIOR_MEMORY_ENABLED"] = settings.prior_memory_enabled
    if settings.decision_weaving_enabled or include_disabled_experimental:
        flags["DECISION_WEAVING_ENABLED"] = (
            settings.decision_weaving_enabled
        )
    if settings.numeric_check_enabled or include_disabled_experimental:
        flags["NUMERIC_CHECK_ENABLED"] = settings.numeric_check_enabled
    if (
        settings.dynamic_capability_enabled
        or include_disabled_experimental
    ):
        flags["DYNAMIC_CAPABILITY_ENABLED"] = (
            settings.dynamic_capability_enabled
        )
    if settings.llm_tool_selection_enabled or include_disabled_experimental:
        flags["LLM_TOOL_SELECTION_ENABLED"] = settings.llm_tool_selection_enabled
    if settings.reflection_enabled or include_disabled_experimental:
        flags["REFLECTION_ENABLED"] = settings.reflection_enabled
    if settings.skill_packs_enabled or include_disabled_experimental:
        flags["SKILL_PACKS_ENABLED"] = settings.skill_packs_enabled
    if settings.semantic_judge_enabled or include_disabled_experimental:
        flags["SEMANTIC_JUDGE_ENABLED"] = settings.semantic_judge_enabled
    if settings.rag_enabled or include_disabled_experimental:
        flags["RAG_ENABLED"] = settings.rag_enabled
    if settings.rerank_enabled or include_disabled_experimental:
        flags["RERANK_ENABLED"] = settings.rerank_enabled
    if settings.rerank_fail_open or include_disabled_experimental:
        flags["RERANK_FAIL_OPEN"] = settings.rerank_fail_open
    return flags


def write_run_manifest(manifest: RunManifest, runs_root: Path) -> Path:
    output = runs_root / manifest.run_id / "manifest.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = manifest.model_dump(mode="json")
    if not manifest.decision_summary:
        payload.pop("decision_summary", None)
    # Preserve the historical manifest shape until a retrieval index actually
    # participates in a run. The model field remains available for comparison
    # once it has a concrete version, without changing fixture-only artifacts.
    if manifest.retrieval_index_version is None:
        payload.pop("retrieval_index_version", None)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2)
    output.write_text(redact(encoded) + "\n", encoding="utf-8")
    return output


def _prompt_hashes(
    prompt_dir: Path,
    *,
    include_semantic_judge: bool,
) -> dict[str, str]:
    hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(prompt_dir.glob("*.md"))
    }
    if not include_semantic_judge:
        # Preserve historical/default manifest identity for a prompt that is
        # unreachable while its default-off gate is disabled.
        hashes.pop("semantic_judge.md", None)
    return hashes


def _config_hash(settings: Settings) -> str:
    payload = {
        key: str(value) if isinstance(value, Path) else value
        for key, value in asdict(settings).items()
    }
    if not settings.branch_budget_enabled and not settings.research_loop_active:
        payload.pop("branch_budget_enabled", None)
        payload.pop("branch_total_budget", None)
        payload.pop("branch_single_cap", None)
    if not settings.research_loop_active:
        payload.pop("research_loop_enabled", None)
        payload.pop("research_loop_max_iterations", None)
        payload.pop("research_loop_budget_ceiling", None)
        payload.pop("research_loop_no_progress_window", None)
        payload.pop("research_min_evidence_count", None)
        payload.pop("research_min_independent_domains", None)
        payload.pop("research_min_average_confidence", None)
        payload.pop("research_max_freshness_age_days", None)
        payload.pop("research_max_unresolved_critic_issues", None)
    if not settings.skill_packs_enabled:
        payload.pop("skill_packs_enabled", None)
    if not settings.prior_memory_enabled:
        payload.pop("prior_memory_enabled", None)
        payload.pop("prior_watch_confidence_threshold", None)
    if not settings.decision_weaving_enabled:
        payload.pop("decision_weaving_enabled", None)
        payload.pop("decision_weaving_budget_remaining_ratio", None)
        payload.pop("decision_weaving_verify_min_allocation", None)
    if not settings.numeric_check_enabled:
        payload.pop("numeric_check_enabled", None)
        payload.pop("numeric_check_relative_tolerance", None)
        payload.pop("numeric_check_absolute_tolerance", None)
    if not settings.dynamic_capability_enabled:
        payload.pop("dynamic_capability_enabled", None)
        payload.pop("dynamic_capability_rules_json", None)
    if not settings.reflection_enabled:
        payload.pop("reflection_enabled", None)
    if not settings.semantic_judge_enabled:
        payload.pop("semantic_judge_enabled", None)
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _dependency_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for package in (
        "deepresearch-agent",
        "langgraph",
        "langgraph-checkpoint-sqlite",
        "litellm",
        "pydantic",
        "fastapi",
        "httpx",
    ):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = "not-installed"
    return versions


def _optional_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        return date.fromisoformat(value)
    return None


def _optional_string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _json_value(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    return value
