from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RoleModelConfig:
    model: str
    api_base: str | None = None


@dataclass(frozen=True)
class LLMConfig:
    temperature: float = 0.0
    timeout_seconds: int = 60
    max_retries: int = 2
    repair_retries: int = 1
    cost_usd_to_cny: float = 7.2
    # DeepSeek's v4-flash naming is the preferred target for the next model cutover.
    # Until LiteLLM/provider naming stabilizes, use OpenAI-compatible DeepSeek API calls.
    # Switch away from deepseek-chat before its announced 2026-07-24 deprecation point.
    roles: dict[str, RoleModelConfig] = field(
        default_factory=lambda: {
            "planner": RoleModelConfig(
                model="openai/deepseek-chat",
                api_base="https://api.deepseek.com",
            ),
            "extractor": RoleModelConfig(
                model="openai/deepseek-chat",
                api_base="https://api.deepseek.com",
            ),
            "reporter": RoleModelConfig(
                model="openai/deepseek-chat",
                api_base="https://api.deepseek.com",
            ),
        }
    )


DEFAULT_LLM_CONFIG = LLMConfig()
