from __future__ import annotations

import hashlib
import importlib.metadata
import json
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

from pydantic import Field

from deepresearch_agent.llm_config import DEFAULT_LLM_CONFIG
from deepresearch_agent.schemas import ResearchState, StrictModel, utc_now
from deepresearch_agent.security import redact
from deepresearch_agent.settings import Settings, project_root


class RunManifest(StrictModel):
    run_id: str
    started_at: datetime
    ended_at: datetime
    model_strings: dict[str, str]
    prompt_hashes: dict[str, str]
    retrieval_corpus_as_of: date | None = None
    evaluation_as_of: date | None = None
    config_hash: str
    dependency_versions: dict[str, str]
    domain: str
    mode: str
    flags: dict[str, bool]
    token_total: int = Field(ge=0)
    cost_cny_total: float = Field(ge=0)
    degradation_events: list[dict[str, Any]] = Field(default_factory=list)
    context_events: list[dict[str, Any]] = Field(default_factory=list)
    tool_error_summary: dict[str, int] = Field(default_factory=dict)


class ManifestComparison(StrictModel):
    comparable: bool
    differences: dict[str, dict[str, Any]] = Field(default_factory=dict)


COMPARABILITY_FIELDS = (
    "model_strings",
    "prompt_hashes",
    "retrieval_corpus_as_of",
    "evaluation_as_of",
    "flags",
    "dependency_versions",
    "domain",
    "mode",
)


def compare_manifests(left: RunManifest, right: RunManifest) -> ManifestComparison:
    """Prevent false improvements caused by changing the judge or run conditions.

    The project previously observed an apparent quality improvement after a
    judge change. This comparison turns that manual lesson into a hard,
    machine-readable comparability decision.
    """

    differences: dict[str, dict[str, Any]] = {}
    for field_name in COMPARABILITY_FIELDS:
        left_value = getattr(left, field_name)
        right_value = getattr(right, field_name)
        if left_value != right_value:
            differences[field_name] = {
                "left": _json_value(left_value),
                "right": _json_value(right_value),
            }
    return ManifestComparison(comparable=not differences, differences=differences)


def build_run_manifest(
    state: ResearchState,
    settings: Settings,
    *,
    started_at: datetime,
    ended_at: datetime | None = None,
    domain: str = "finance",
) -> RunManifest:
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
            role: config.model for role, config in DEFAULT_LLM_CONFIG.roles.items()
        },
        prompt_hashes=_prompt_hashes(root / "prompts"),
        retrieval_corpus_as_of=_optional_date(metadata.get("retrieval_corpus_as_of"))
        or settings.as_of,
        evaluation_as_of=_optional_date(metadata.get("evaluation_as_of")) or settings.as_of,
        config_hash=_config_hash(settings),
        dependency_versions=_dependency_versions(),
        domain=domain,
        mode=settings.execution_mode,
        flags={
            "TOOL_CONTRACT_ENABLED": settings.tool_contract_enabled,
            "INJECTION_GUARD_ENABLED": settings.injection_guard_enabled,
            "RUN_MANIFEST_ENABLED": settings.run_manifest_enabled,
            "CONTEXT_PACKER_ENABLED": settings.context_packer_enabled,
        },
        token_total=state.token_used,
        cost_cny_total=state.cost_used,
        degradation_events=degradation_events,
        context_events=context_events,
        tool_error_summary={str(key): int(value) for key, value in tool_errors.items()},
    )


def write_run_manifest(manifest: RunManifest, runs_root: Path) -> Path:
    output = runs_root / manifest.run_id / "manifest.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2)
    output.write_text(redact(encoded) + "\n", encoding="utf-8")
    return output


def _prompt_hashes(prompt_dir: Path) -> dict[str, str]:
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(prompt_dir.glob("*.md"))
    }


def _config_hash(settings: Settings) -> str:
    payload = {
        key: str(value) if isinstance(value, Path) else value
        for key, value in asdict(settings).items()
    }
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


def _json_value(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    return value
