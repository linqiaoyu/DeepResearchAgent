from __future__ import annotations

import os
from collections.abc import Mapping

from deepresearch_agent.settings import Settings


class ConfigurationError(ValueError):
    def __init__(self, missing: list[str]) -> None:
        self.missing = sorted(set(missing))
        super().__init__("Missing required configuration: " + ", ".join(self.missing))


def validate_required_configuration(
    settings: Settings,
    environ: Mapping[str, str] | None = None,
) -> None:
    env = os.environ if environ is None else environ
    missing: list[str] = []
    if settings.execution_mode == "llm" and not env.get("DEEPSEEK_API_KEY", "").strip():
        missing.append("DEEPSEEK_API_KEY")
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
