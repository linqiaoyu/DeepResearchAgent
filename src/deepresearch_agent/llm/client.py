from __future__ import annotations

import json
import time
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from deepresearch_agent.llm_config import DEFAULT_LLM_CONFIG, LLMConfig
from deepresearch_agent.settings import project_root

SchemaT = TypeVar("SchemaT", bound=BaseModel)


class LLMClientError(RuntimeError):
    pass


class StructuredOutputError(LLMClientError):
    pass


class BudgetExceededError(LLMClientError):
    def __init__(self, run_id: str, budget_cny: float, actual_cny: float) -> None:
        super().__init__(
            f"LLM budget exceeded for run_id={run_id}: actual_cny={actual_cny:.6f} "
            f"budget_cny={budget_cny:.6f}"
        )
        self.run_id = run_id
        self.budget_cny = budget_cny
        self.actual_cny = actual_cny


@dataclass(frozen=True)
class LLMCallResult:
    content: str
    parsed: BaseModel | None
    model: str
    prompt_tokens: int
    prompt_cache_hit_tokens: int
    prompt_cache_miss_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float
    cost_cny: float
    price_source: str
    latency_seconds: float
    cache_hit: bool | None
    repair_attempts: int = 0


class LLMClient:
    def __init__(
        self,
        ledger_path: Path,
        budget_cny: float,
        config: LLMConfig = DEFAULT_LLM_CONFIG,
        completion_func: Any | None = None,
        sleep_func: Any = time.sleep,
        env_path: Path | None = None,
        global_ledger_path: Path | None = None,
    ) -> None:
        self._litellm = None if completion_func is not None else self._load_litellm()
        self.ledger_path = ledger_path
        self.global_ledger_path = global_ledger_path or project_root() / "data" / "runtime" / "llm_ledger.jsonl"
        self.budget_cny = budget_cny
        self.config = config
        self._completion = completion_func or self._litellm.completion
        self._sleep = sleep_func
        self._env_path = env_path or project_root() / ".env"
        self._run_costs_cny: dict[str, float] = {}
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self.global_ledger_path.parent.mkdir(parents=True, exist_ok=True)

    def start_run(self, run_id: str) -> None:
        self._run_costs_cny[run_id] = self._ledger_cost_for_run(run_id)

    def complete(
        self,
        *,
        role: str,
        messages: list[dict[str, str]],
        run_id: str,
        schema: type[SchemaT] | None = None,
    ) -> LLMCallResult:
        if run_id not in self._run_costs_cny:
            self.start_run(run_id)
        role_config = self.config.roles.get(role)
        if not role_config:
            raise LLMClientError(f"No LLM model configured for role={role}")
        api_key = self._api_key(role_config.api_key_env)

        prompt_messages = list(messages)
        if schema:
            prompt_messages.append(
                {
                    "role": "system",
                    "content": (
                        "Return only valid JSON matching this JSON Schema. "
                        f"Schema: {json.dumps(schema.model_json_schema(), ensure_ascii=False)}"
                    ),
                }
            )

        first_error: str | None = None
        raw_result = self._completion_with_retries(
            role=role,
            model=role_config.model,
            fallback_model=role_config.fallback_model,
            api_base=role_config.api_base,
            api_key=api_key,
            messages=prompt_messages,
        )
        content = raw_result.content
        parsed: BaseModel | None = None
        repair_attempts = 0
        if schema:
            try:
                parsed = self._parse_schema(content, schema)
            except StructuredOutputError as exc:
                first_error = str(exc)
                self._record_ledger(
                    run_id=run_id,
                    role=role,
                    result=raw_result,
                    structured=True,
                    parse_error=first_error,
                )
                self._run_costs_cny[run_id] += raw_result.cost_cny
                if self._run_costs_cny[run_id] > self.budget_cny:
                    raise BudgetExceededError(run_id, self.budget_cny, self._run_costs_cny[run_id])
                repair_attempts = 1
                repair_messages = [
                    *prompt_messages,
                    {"role": "assistant", "content": content},
                    {
                        "role": "user",
                        "content": (
                            "The previous JSON failed validation. Correct it and return only valid JSON. "
                            f"Validation error: {first_error}"
                        ),
                    },
                ]
                raw_result = self._completion_with_retries(
                    role=role,
                    model=role_config.model,
                    fallback_model=role_config.fallback_model,
                    api_base=role_config.api_base,
                    api_key=api_key,
                    messages=repair_messages,
                    is_repair=True,
                )
                content = raw_result.content
                parsed = self._parse_schema(content, schema)

        result = LLMCallResult(
            content=content,
            parsed=parsed,
            model=raw_result.model,
            prompt_tokens=raw_result.prompt_tokens,
            prompt_cache_hit_tokens=raw_result.prompt_cache_hit_tokens,
            prompt_cache_miss_tokens=raw_result.prompt_cache_miss_tokens,
            completion_tokens=raw_result.completion_tokens,
            total_tokens=raw_result.total_tokens,
            cost_usd=raw_result.cost_usd,
            cost_cny=raw_result.cost_cny,
            price_source=raw_result.price_source,
            latency_seconds=raw_result.latency_seconds,
            cache_hit=raw_result.cache_hit,
            repair_attempts=repair_attempts,
        )
        self._record_ledger(
            run_id=run_id,
            role=role,
            result=result,
            structured=bool(schema),
            parse_error=first_error,
        )
        self._run_costs_cny[run_id] += result.cost_cny
        if self._run_costs_cny[run_id] > self.budget_cny:
            raise BudgetExceededError(run_id, self.budget_cny, self._run_costs_cny[run_id])
        return result

    def run_total_cny(self, run_id: str) -> float:
        if run_id not in self._run_costs_cny:
            self.start_run(run_id)
        return self._run_costs_cny[run_id]

    def ledger_total_cny(self) -> float:
        total = 0.0
        for row in self._iter_ledger_rows(self.global_ledger_path):
            total += float(row.get("cost_cny", 0.0))
        return total

    def aggregate_run(self, run_id: str) -> dict[str, Any]:
        rows = [
            row for row in self._iter_ledger_rows(self.global_ledger_path) if row.get("run_id") == run_id
        ]
        by_role: dict[str, dict[str, float | int]] = {}
        for row in rows:
            role = str(row.get("role", "unknown"))
            bucket = by_role.setdefault(
                role,
                {
                    "calls": 0,
                    "prompt_tokens": 0,
                    "prompt_cache_hit_tokens": 0,
                    "prompt_cache_miss_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "cost_usd": 0.0,
                    "cost_cny": 0.0,
                    "latency_seconds": 0.0,
                },
            )
            bucket["calls"] = int(bucket["calls"]) + 1
            for key in (
                "prompt_tokens",
                "prompt_cache_hit_tokens",
                "prompt_cache_miss_tokens",
                "completion_tokens",
                "total_tokens",
            ):
                bucket[key] = int(bucket[key]) + int(row.get(key, 0))
            for key in ("cost_usd", "cost_cny", "latency_seconds"):
                bucket[key] = float(bucket[key]) + float(row.get(key, 0.0))
        return {
            "rows": rows,
            "by_role": by_role,
            "total_cost_cny": sum(float(r.get("cost_cny", 0.0)) for r in rows),
            "price_source": self.config.price_source,
        }

    def _completion_with_retries(
        self,
        *,
        role: str,
        model: str,
        fallback_model: str | None,
        api_base: str | None,
        api_key: str,
        messages: list[dict[str, str]],
        is_repair: bool = False,
    ) -> LLMCallResult:
        last_error: Exception | None = None
        candidate_models = [model]
        if fallback_model and fallback_model != model:
            candidate_models.append(fallback_model)
        for candidate_model in candidate_models:
            for attempt in range(self.config.max_retries + 1):
                started = time.perf_counter()
                try:
                    response = self._completion(
                        model=candidate_model,
                        messages=messages,
                        temperature=self.config.temperature,
                        timeout=self.config.timeout_seconds,
                        api_key=api_key,
                        api_base=api_base,
                    )
                    latency = time.perf_counter() - started
                    content = self._message_content(response)
                    usage = self._usage(response)
                    cost_cny = self._cost_cny(usage)
                    return LLMCallResult(
                        content=content,
                        parsed=None,
                        model=candidate_model,
                        prompt_tokens=usage["prompt_tokens"],
                        prompt_cache_hit_tokens=usage["prompt_cache_hit_tokens"],
                        prompt_cache_miss_tokens=usage["prompt_cache_miss_tokens"],
                        completion_tokens=usage["completion_tokens"],
                        total_tokens=usage["total_tokens"],
                        cost_usd=cost_cny * self.config.display_cny_to_usd_rate,
                        cost_cny=cost_cny,
                        price_source=self.config.price_source,
                        latency_seconds=latency,
                        cache_hit=self._cache_hit(response),
                        repair_attempts=1 if is_repair else 0,
                    )
                except Exception as exc:  # litellm exceptions are provider-specific.
                    last_error = exc
                    if attempt >= self.config.max_retries:
                        break
                    self._sleep(2**attempt)
        raise LLMClientError(f"LLM call failed for role={role}: {last_error}")

    def _api_key(self, key_name: str) -> str:
        if not self._env_path.exists():
            raise LLMClientError(f"Missing .env with {key_name}.")
        for line in self._env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            if key.strip() == key_name and value.strip():
                return value.strip().strip('"').strip("'")
        raise LLMClientError(f"Missing {key_name} in .env.")

    def _parse_schema(self, content: str, schema: type[SchemaT]) -> SchemaT:
        try:
            return schema.model_validate_json(self._json_payload(content))
        except (ValidationError, ValueError, json.JSONDecodeError) as exc:
            raise StructuredOutputError(str(exc)) from exc

    def _json_payload(self, content: str) -> str:
        text = content.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        return text

    def _message_content(self, response: Any) -> str:
        choice = response["choices"][0] if isinstance(response, dict) else response.choices[0]
        message = choice["message"] if isinstance(choice, dict) else choice.message
        content = message["content"] if isinstance(message, dict) else message.content
        return content or ""

    def _usage(self, response: Any) -> dict[str, int]:
        usage = response.get("usage", {}) if isinstance(response, dict) else getattr(response, "usage", {})
        getter = usage.get if isinstance(usage, dict) else lambda key, default=0: getattr(usage, key, default)
        prompt_tokens = int(getter("prompt_tokens", 0) or 0)
        completion_tokens = int(getter("completion_tokens", 0) or 0)
        total_tokens = int(getter("total_tokens", prompt_tokens + completion_tokens) or 0)
        prompt_cache_hit_tokens = int(
            getter("prompt_cache_hit_tokens", None)
            or getter("cached_tokens", None)
            or self._nested_cached_tokens(getter("prompt_tokens_details", None))
            or 0
        )
        prompt_cache_hit_tokens = min(prompt_cache_hit_tokens, prompt_tokens)
        prompt_cache_miss_tokens = max(0, prompt_tokens - prompt_cache_hit_tokens)
        return {
            "prompt_tokens": prompt_tokens,
            "prompt_cache_hit_tokens": prompt_cache_hit_tokens,
            "prompt_cache_miss_tokens": prompt_cache_miss_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        }

    def _nested_cached_tokens(self, value: Any) -> int:
        if value is None:
            return 0
        if isinstance(value, dict):
            return int(value.get("cached_tokens", 0) or 0)
        return int(getattr(value, "cached_tokens", 0) or 0)

    def _cost_cny(self, usage: dict[str, int]) -> float:
        input_cost = (
            usage["prompt_cache_miss_tokens"] * self.config.input_cache_miss_cny_per_million
            + usage["prompt_cache_hit_tokens"] * self.config.input_cache_hit_cny_per_million
        )
        output_cost = usage["completion_tokens"] * self.config.output_cny_per_million
        return (input_cost + output_cost) / 1_000_000

    def _cache_hit(self, response: Any) -> bool | None:
        headers = response.get("_hidden_params", {}).get("additional_headers", {}) if isinstance(response, dict) else {}
        if not headers:
            return None
        value = headers.get("x-litellm-cache-hit") or headers.get("x-cache")
        if value is None:
            return None
        return str(value).lower() in {"true", "hit", "1"}

    def _record_ledger(
        self,
        *,
        run_id: str,
        role: str,
        result: LLMCallResult,
        structured: bool,
        parse_error: str | None,
    ) -> None:
        row = {
            "run_id": run_id,
            "role": role,
            "model": result.model,
            "prompt_tokens": result.prompt_tokens,
            "input_tokens": result.prompt_tokens,
            "prompt_cache_hit_tokens": result.prompt_cache_hit_tokens,
            "prompt_cache_miss_tokens": result.prompt_cache_miss_tokens,
            "completion_tokens": result.completion_tokens,
            "output_tokens": result.completion_tokens,
            "total_tokens": result.total_tokens,
            "cost_usd": round(result.cost_usd, 8),
            "cost_cny": round(result.cost_cny, 8),
            "price_source": result.price_source,
            "latency_seconds": round(result.latency_seconds, 3),
            "cache_hit": result.cache_hit,
            "structured": structured,
            "repair_attempts": result.repair_attempts,
            "parse_error": bool(parse_error),
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        encoded = json.dumps(row, ensure_ascii=False) + "\n"
        ledger_paths = [self.global_ledger_path]
        if self.ledger_path.resolve() != self.global_ledger_path.resolve():
            ledger_paths.append(self.ledger_path)
        for path in ledger_paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as file:
                file.write(encoded)

    def _ledger_cost_for_run(self, run_id: str) -> float:
        return sum(
            float(row.get("cost_cny", 0.0))
            for row in self._iter_ledger_rows(self.global_ledger_path)
            if row.get("run_id") == run_id
        )

    def _iter_ledger_rows(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows

    def _load_litellm(self) -> Any:
        try:
            return import_module("litellm")
        except ModuleNotFoundError as exc:  # pragma: no cover - exercised only in misconfigured envs.
            raise LLMClientError("litellm is not installed.") from exc
