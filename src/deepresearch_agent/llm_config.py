from __future__ import annotations

from dataclasses import dataclass, field


# Retrieval model identifiers are kept here with the chat-role models so
# provider implementations never embed a model name in workflow code.
DASHSCOPE_EMBEDDING_MODEL = "text-embedding-v4"
DASHSCOPE_RERANK_MODEL = "qwen3-rerank"
DASHSCOPE_EMBEDDING_ENDPOINT = "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"
DASHSCOPE_RERANK_ENDPOINT = "https://dashscope.aliyuncs.com/compatible-api/v1/reranks"


@dataclass(frozen=True)
class RoleModelConfig:
    model: str
    fallback_model: str | None = None
    api_base: str | None = None
    api_key_env: str = "DEEPSEEK_API_KEY"
    timeout_seconds: int | None = None
    max_completion_tokens: int = 8192


@dataclass(frozen=True)
class ModelPricing:
    max_prompt_tokens: int | None
    input_cache_miss_cny_per_million: float
    input_cache_hit_cny_per_million: float
    output_cny_per_million: float
    price_source: str


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
    pricing_by_model: dict[str, tuple[ModelPricing, ...]] = field(
        default_factory=lambda: {
            "openai/deepseek-v4-flash": (
                ModelPricing(
                    max_prompt_tokens=None,
                    input_cache_miss_cny_per_million=1.0,
                    input_cache_hit_cny_per_million=0.02,
                    output_cny_per_million=2.0,
                    price_source="v4flash_console_calibrated_20260612",
                ),
            ),
            "openai/deepseek-v4-pro": (
                ModelPricing(
                    max_prompt_tokens=None,
                    input_cache_miss_cny_per_million=3.0,
                    input_cache_hit_cny_per_million=0.025,
                    output_cny_per_million=6.0,
                    price_source="deepseek_official_cny_20260726",
                ),
            ),
            "openai/qwen3.7-plus": (
                ModelPricing(
                    max_prompt_tokens=256_000,
                    input_cache_miss_cny_per_million=2.0,
                    input_cache_hit_cny_per_million=0.4,
                    output_cny_per_million=8.0,
                    price_source="aliyun_bailian_cn_beijing_20260725",
                ),
                ModelPricing(
                    max_prompt_tokens=1_000_000,
                    input_cache_miss_cny_per_million=6.0,
                    input_cache_hit_cny_per_million=1.2,
                    output_cny_per_million=24.0,
                    price_source="aliyun_bailian_cn_beijing_20260725",
                ),
            ),
        }
    )
    # Model names are explicit and centralized here; do not rely on provider aliases.
    roles: dict[str, RoleModelConfig] = field(
        default_factory=lambda: {
            "planner": RoleModelConfig(
                model="openai/deepseek-v4-flash",
                api_base="https://api.deepseek.com",
            ),
            "extractor": RoleModelConfig(
                model="openai/deepseek-v4-flash",
                api_base="https://api.deepseek.com",
            ),
            "capability_selector": RoleModelConfig(
                model="openai/deepseek-v4-flash",
                api_base="https://api.deepseek.com",
            ),
            "reporter": RoleModelConfig(
                model="openai/deepseek-v4-flash",
                api_base="https://api.deepseek.com",
            ),
            "judge": RoleModelConfig(
                model="openai/qwen3.7-plus",
                api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
                api_key_env="DASHSCOPE_API_KEY",
                timeout_seconds=300,
            ),
            "citation_support": RoleModelConfig(
                model="openai/qwen3.7-plus",
                api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
                api_key_env="DASHSCOPE_API_KEY",
                timeout_seconds=300,
            ),
        }
    )


DEFAULT_LLM_CONFIG = LLMConfig()
