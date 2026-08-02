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
