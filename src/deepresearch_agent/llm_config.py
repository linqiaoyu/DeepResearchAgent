from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any


# R099: the request body that makes this endpoint stop reasoning. Measured, not
# guessed -- `_collab/099/evidence/probe_exhaustion_fix.log` ran one identical
# request under four controls at a cap the baseline exhausts:
#
#   baseline                          finish_reason=length content=0    reasoning=400/400
#   reasoning_effort=minimal          finish_reason=length content=0    reasoning=400/400
#   extra_body.thinking=disabled      finish_reason=length content=1581 reasoning=0
#   extra_body.enable_thinking=false  finish_reason=length content=0    reasoning=400/400
#
# `reasoning_effort` is forwarded by litellm once `allowed_openai_params` names
# it -- R098 read its rejection as the model's and concluded bounding the
# thinking was not a one-line setting -- but the endpoint ignores it. Passing
# `thinking` as a top-level parameter is rejected by the OpenAI SDK itself
# (`Completions.create() got an unexpected keyword argument`). Only the
# `extra_body` spelling below changes what comes back.
#
# Kept read-only because it is shared by every role that references it.
DISABLE_REASONING_EXTRA_BODY: Mapping[str, Any] = MappingProxyType(
    {"thinking": MappingProxyType({"type": "disabled"})}
)


# Retrieval model identifiers are kept here with the chat-role models so
# provider implementations never embed a model name in workflow code.
DASHSCOPE_EMBEDDING_MODEL = "text-embedding-v4"
DASHSCOPE_RERANK_MODEL = "qwen3-rerank"
DASHSCOPE_EMBEDDING_ENDPOINT = "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"
# DashScope rerank endpoint documented at https://help.aliyun.com/zh/model-studio/rerank-api-reference .
DASHSCOPE_RERANK_ENDPOINT = "https://dashscope.aliyuncs.com/compatible-api/v1/reranks"


@dataclass(frozen=True)
class RoleModelConfig:
    model: str
    fallback_model: str | None = None
    api_base: str | None = None
    api_key_env: str = "DEEPSEEK_API_KEY"
    timeout_seconds: int | None = None
    max_completion_tokens: int = 8192
    #: Request body that makes this role's endpoint stop reasoning, or ``None``
    #: when no such body has been measured for it. The client sends it only to
    #: recover a call that spent its whole completion budget thinking, so a role
    #: keeps its reasoning for as long as the reasoning leaves room to answer.
    #: Left ``None`` for the DashScope roles: their endpoint was never probed,
    #: and sending a body measured against a different provider would be a guess
    #: dressed as a fix.
    no_reasoning_extra_body: Mapping[str, Any] | None = None


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
                # R090 and the R149 full cohort both observed three consecutive
                # provider calls terminated at the inherited 60s boundary.
                # Planner output is bounded by its schema and token cap; give
                # transport latency the same hard bound as other generation roles.
                timeout_seconds=180,
                no_reasoning_extra_body=DISABLE_REASONING_EXTRA_BODY,
            ),
            # R073/R075 bounded these two roles for latency. The input bounds
            # (12k prompt chars, 18 evidence entries) fixed the timeout and are
            # kept; the 1024-token completion cap did not, and truncated every
            # structured response from R073 to R089 into a silent fallback.
            # R090 raised it to 4096 from an estimate; the first live run that
            # reached a provider measured both roles emitting exactly 4096 with
            # `finish_reason=length`, so the estimate was still short. Both now
            # use the 8192 default, and `prompts/` bounds the response to what
            # the renderer actually consumes so the cap is headroom, not a
            # target.
            "extractor": RoleModelConfig(
                model="openai/deepseek-v4-flash",
                api_base="https://api.deepseek.com",
                timeout_seconds=180,
                no_reasoning_extra_body=DISABLE_REASONING_EXTRA_BODY,
            ),
            "capability_selector": RoleModelConfig(
                model="openai/deepseek-v4-flash",
                api_base="https://api.deepseek.com",
                no_reasoning_extra_body=DISABLE_REASONING_EXTRA_BODY,
            ),
            "reporter": RoleModelConfig(
                model="openai/deepseek-v4-flash",
                api_base="https://api.deepseek.com",
                timeout_seconds=180,
                no_reasoning_extra_body=DISABLE_REASONING_EXTRA_BODY,
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
