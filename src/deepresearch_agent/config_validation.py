from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from deepresearch_agent.settings import Settings, project_root


class ConfigurationError(ValueError):
    def __init__(self, missing: list[str]) -> None:
        self.missing = sorted(set(missing))
        super().__init__("Missing required configuration: " + ", ".join(self.missing))


class ConfigurationInvariantError(ValueError):
    """Raised when enabled features violate a required safety invariant."""


def validate_security_invariants(settings: Settings) -> None:
    """Validate safety properties that operational flags must not bypass."""
    if settings.rag_enabled and not settings.injection_guard_enabled:
        raise ConfigurationInvariantError(
            "INJECTION_GUARD_ENABLED must be true when RAG_ENABLED is true"
        )


def validate_capability_invariants(
    settings: Settings,
    environ: Mapping[str, str] | None = None,
) -> None:
    """Refuse a capability that is switched on but cannot take effect.

    R109: every guard reads ``Settings.research_loop_active``, which requires
    ``research_loop_max_iterations > 1``, and that setting defaults to 1. So
    ``RESEARCH_LOOP_ENABLED=true`` on its own changed nothing at all -- the
    documented flag table says the capability exists, the operator turns it on,
    and the run behaves exactly as before with nothing reported. A capability
    that is on and inert is worse than one that is off, because only the second
    is honest about it.
    """

    if settings.research_loop_enabled and settings.research_loop_max_iterations <= 1:
        raise ConfigurationInvariantError(
            "RESEARCH_LOOP_ENABLED requires DEEPRESEARCH_RESEARCH_LOOP_MAX_ITERATIONS "
            f"> 1; got {settings.research_loop_max_iterations}"
        )
    # R110 note: `RAG_ENABLED=true` with no configured backend is refused too,
    # but by `rag.factory.build_rag_search` rather than here. The engine accepts
    # an injected retrieval service, and a check at this layer cannot see that
    # injection -- it would refuse a run whose backend was supplied in code.
    # The refusal still happens at engine construction, one layer later.


def validate_required_configuration(
    settings: Settings,
    environ: Mapping[str, str] | None = None,
    env_path: Path | None = None,
) -> None:
    # Runtime callers use the same project .env fallback as LLMClient.  An
    # injected mapping remains self-contained for deterministic tests.
    env = (
        _environment_with_dotenv(env_path or project_root() / ".env")
        if environ is None
        else environ
    )
    missing: list[str] = []
    if settings.execution_mode == "llm" and not env.get("DEEPSEEK_API_KEY", "").strip():
        missing.append("DEEPSEEK_API_KEY")
    if (
        settings.execution_mode == "llm"
        and settings.semantic_judge_enabled
        and not env.get("DASHSCOPE_API_KEY", "").strip()
    ):
        missing.append("DASHSCOPE_API_KEY")
    validate_security_invariants(settings)
    validate_capability_invariants(settings, env)
    search_provider = env.get("DEEPRESEARCH_SEARCH_PROVIDER", "fixture").strip().lower()
    if search_provider == "tavily" and not env.get("TAVILY_API_KEY", "").strip():
        missing.append("TAVILY_API_KEY")
    if env.get("DEEPRESEARCH_REQUIRE_DEMO_OWNER", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    } and not env.get("DEEPRESEARCH_DEMO_OWNER_TOKEN", "").strip():
        missing.append("DEEPRESEARCH_DEMO_OWNER_TOKEN")
    if missing:
        raise ConfigurationError(missing)


def _environment_with_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if path.exists():
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    values.update(os.environ)
    return values
