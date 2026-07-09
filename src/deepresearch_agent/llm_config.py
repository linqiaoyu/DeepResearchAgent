from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RoleModelConfig:
    model: str
    fallback_model: str | None = None
    api_base: str | None = None
    api_key_env: str = "DEEPSEEK_API_KEY"


@dataclass(frozen=True)
class LLMConfig:
    temperature: float = 0.0
    timeout_seconds: int = 60
    max_retries: int = 2
    repair_retries: int = 1
    price_source: str = "v4flash_console_calibrated_20260612"
    input_cache_miss_cny_per_million: float = 1.0
    input_cache_hit_cny_per_million: float = 0.02
    output_cny_per_million: float = 2.0
    display_cny_to_usd_rate: float = 0.14
    # Primary model is explicit deepseek-v4-flash via the OpenAI-compatible API.
    # If the provider rejects that name, the client falls back to deepseek-chat;
    # DeepSeek currently routes that alias to v4-flash billing per console calibration.
    roles: dict[str, RoleModelConfig] = field(
        default_factory=lambda: {
            "planner": RoleModelConfig(
                model="openai/deepseek-v4-flash",
                fallback_model="openai/deepseek-chat",
                api_base="https://api.deepseek.com",
            ),
            "extractor": RoleModelConfig(
                model="openai/deepseek-v4-flash",
                fallback_model="openai/deepseek-chat",
                api_base="https://api.deepseek.com",
            ),
            "reporter": RoleModelConfig(
                model="openai/deepseek-v4-flash",
                fallback_model="openai/deepseek-chat",
                api_base="https://api.deepseek.com",
            ),
            "judge": RoleModelConfig(
                model="openai/qwen3.7-plus",
                api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
                api_key_env="DASHSCOPE_API_KEY",
            ),
            "citation_support": RoleModelConfig(
                model="openai/qwen3.7-plus",
                api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
                api_key_env="DASHSCOPE_API_KEY",
            ),
        }
    )


DEFAULT_LLM_CONFIG = LLMConfig()
