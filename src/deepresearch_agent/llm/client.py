from __future__ import annotations

import json
import multiprocessing
import os
import queue
import signal
import threading
import time
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any, Callable, TypeVar

from pydantic import BaseModel, ValidationError

from deepresearch_agent.llm_config import DEFAULT_LLM_CONFIG, LLMConfig
from deepresearch_agent.observability import JsonLogger, correlation_context
from deepresearch_agent.security import redact
from deepresearch_agent.settings import project_root
from deepresearch_agent.trajectory import LLMCallTrace, active_trajectory_recorder

SchemaT = TypeVar("SchemaT", bound=BaseModel)


# A transport timeout is necessary but insufficient: a provider SDK can still
# block while consuming a response.  Keep at most this many overdue calls
# quarantined, and make their workers daemonic so they cannot hold a workflow
# (or interpreter shutdown) hostage.
_MAX_DETACHED_LLM_CALLS = 16
_LLM_CALL_SLOTS = threading.BoundedSemaphore(_MAX_DETACHED_LLM_CALLS)


# Importing the provider SDK is local work, not a provider transport. Charging
# it to a role's call timeout made a slow host unable to complete any call at
# all, so worker startup gets its own budget.
_WORKER_STARTUP_TIMEOUT_SECONDS = float(
    os.getenv("DEEPRESEARCH_PROVIDER_WORKER_STARTUP_TIMEOUT", "900")
)


def _response_payload(response: Any) -> Any:
    if isinstance(response, dict):
        return response
    if callable(model_dump := getattr(response, "model_dump", None)):
        return model_dump()
    if callable(to_dict := getattr(response, "dict", None)):
        return to_dict()
    return json.loads(response.json())


def _litellm_subprocess_worker(
    kwargs: dict[str, Any],
    result_queue: Any,
) -> None:
    """Run one production LiteLLM request in a killable child process."""
    try:
        litellm = import_module("litellm")
        result_queue.put(("ok", _response_payload(litellm.completion(**kwargs))))
    except BaseException as exc:
        result_queue.put(("error", f"{type(exc).__name__}: {exc}"))


def _litellm_worker_loop(
    request_queue: Any,
    response_queue: Any,
    ready_queue: Any,
) -> None:
    """Import the provider SDK once, then serve requests until told to stop.

    One import per worker instead of one per call. The worker stays killable:
    the parent terminates it whenever a call overruns its deadline, and never
    reuses a worker whose response never arrived.
    """

    started = time.monotonic()
    try:
        litellm = import_module("litellm")
    except BaseException as exc:  # pragma: no cover - import failure is fatal
        ready_queue.put(("error", f"{type(exc).__name__}: {exc}"))
        return
    # Deliberately no warm-up call here: a `mock_response` completion measured
    # at 9ms left the SDK in a state where the first real request took 74s,
    # against 1.4s without it. Import, report, and let the first real request be
    # the first request.
    ready_queue.put(
        ("ok", {"import_seconds": round(time.monotonic() - started, 3)})
    )
    while True:
        request = request_queue.get()
        if request is None:
            return
        try:
            response_queue.put(("ok", _response_payload(litellm.completion(**request))))
        except BaseException as exc:
            response_queue.put(("error", f"{type(exc).__name__}: {exc}"))


class _ProviderWorker:
    """One spawned process serving provider calls for one caller thread.

    Workers are per-thread so branch fan-out keeps its parallelism; a single
    shared worker would serialize every branch behind one provider call.
    """

    def __init__(
        self,
        *,
        worker_loop: Callable[[Any, Any, Any], None],
        startup_timeout_seconds: float,
    ) -> None:
        context = multiprocessing.get_context("spawn")
        self._request_queue = context.Queue(maxsize=1)
        self._response_queue = context.Queue(maxsize=1)
        self._ready_queue = context.Queue(maxsize=1)
        self.process = context.Process(
            target=worker_loop,
            args=(self._request_queue, self._response_queue, self._ready_queue),
            daemon=True,
        )
        started = time.monotonic()
        self.process.start()
        try:
            status, detail = self._ready_queue.get(timeout=startup_timeout_seconds)
        except queue.Empty:
            self.terminate()
            raise TimeoutError(
                "provider worker did not become ready within "
                f"{startup_timeout_seconds:g}s"
            ) from None
        if status != "ok":
            self.terminate()
            raise RuntimeError(f"provider worker failed to start: {detail}")
        self.startup_seconds = round(time.monotonic() - started, 3)
        self.startup_detail = detail if isinstance(detail, dict) else {}

    def call(self, kwargs: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
        self._request_queue.put(kwargs)
        try:
            status, payload = self._response_queue.get(timeout=timeout_seconds)
        except queue.Empty:
            self.terminate()
            raise TimeoutError(
                f"LLM operation timed out after {timeout_seconds:g}s; "
                "provider subprocess terminated"
            ) from None
        if status == "error":
            raise RuntimeError(str(payload))
        if not isinstance(payload, dict):
            raise RuntimeError("LiteLLM subprocess returned a non-object response")
        return payload

    def terminate(self) -> None:
        if self.process.is_alive():
            self.process.terminate()
            self.process.join(timeout=5)

    @property
    def alive(self) -> bool:
        return self.process.is_alive()


class _ProviderWorkerPool:
    """Keep one ready worker per caller thread, replacing it after a timeout."""

    def __init__(
        self,
        *,
        worker_loop: Callable[[Any, Any, Any], None] = _litellm_worker_loop,
        startup_timeout_seconds: float = _WORKER_STARTUP_TIMEOUT_SECONDS,
    ) -> None:
        self._worker_loop = worker_loop
        self._startup_timeout_seconds = startup_timeout_seconds
        self._workers: dict[int, _ProviderWorker] = {}
        self._lock = threading.Lock()
        self.spawns = 0
        #: Startup cost of every worker this pool created, so a slow host shows
        #: up as a number instead of an unexplained timeout.
        self.startup_records: list[dict[str, Any]] = []

    def call(self, kwargs: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
        worker = self._acquire()
        try:
            return worker.call(kwargs, timeout_seconds)
        except TimeoutError:
            # `call` already terminated it. Drop the handle so the next call
            # cannot read a late response belonging to this one.
            self._discard(worker)
            raise

    def _acquire(self) -> _ProviderWorker:
        key = threading.get_ident()
        with self._lock:
            worker = self._workers.get(key)
            if worker is not None and worker.alive:
                return worker
            self._workers.pop(key, None)
        created = _ProviderWorker(
            worker_loop=self._worker_loop,
            startup_timeout_seconds=self._startup_timeout_seconds,
        )
        with self._lock:
            self._workers[key] = created
            self.spawns += 1
            self.startup_records.append(
                {
                    "startup_seconds": getattr(created, "startup_seconds", None),
                    **getattr(created, "startup_detail", {}),
                }
            )
        return created

    def _discard(self, worker: _ProviderWorker) -> None:
        with self._lock:
            for key, candidate in list(self._workers.items()):
                if candidate is worker:
                    del self._workers[key]

    def close(self) -> None:
        with self._lock:
            workers = list(self._workers.values())
            self._workers.clear()
        for worker in workers:
            worker.terminate()


class LLMClientError(RuntimeError):
    pass


class LLMRetryExhaustedError(LLMClientError):
    """A provider call exhausted its configured retry budget."""


class StructuredOutputError(LLMClientError):
    #: One of ``invalid_json``, ``schema_violation`` or ``truncated``.
    kind: str = "invalid_json"


class StructuredOutputTruncatedError(StructuredOutputError):
    """The provider stopped at ``max_completion_tokens`` before closing the JSON.

    This is a configuration failure, not a model failure: a repair attempt under
    the same completion cap re-truncates at the same boundary, so the call must
    surface instead of silently paying for a second identical truncation.
    """

    def __init__(
        self,
        *,
        role: str,
        completion_tokens: int,
        max_completion_tokens: int,
        finish_reason: str | None,
    ) -> None:
        super().__init__(
            f"structured output truncated for role={role}: "
            f"completion_tokens={completion_tokens} "
            f"max_completion_tokens={max_completion_tokens} "
            f"finish_reason={finish_reason}"
        )
        self.kind = "truncated"
        self.role = role
        self.completion_tokens = completion_tokens
        self.max_completion_tokens = max_completion_tokens
        self.finish_reason = finish_reason


class BudgetExceededError(LLMClientError):
    def __init__(self, run_id: str, budget_cny: float, actual_cny: float) -> None:
        super().__init__(
            f"LLM budget exceeded for run_id={run_id}: actual_cny={actual_cny:.6f} "
            f"budget_cny={budget_cny:.6f}"
        )
        self.run_id = run_id
        self.budget_cny = budget_cny
        self.actual_cny = actual_cny


class CostOverrunError(LLMClientError):
    def __init__(
        self,
        run_id: str,
        estimated_cny: float,
        actual_cny: float,
    ) -> None:
        super().__init__(
            f"LLM single-call cost overrun for run_id={run_id}: "
            f"actual_cny={actual_cny:.6f} estimated_cny={estimated_cny:.6f} "
            "threshold_multiplier=2"
        )
        self.run_id = run_id
        self.estimated_cny = estimated_cny
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
    tool_calls: tuple[dict[str, Any], ...] = ()
    finish_reason: str | None = None


class LLMClient:
    fidelity = "real"
    def __init__(
        self,
        ledger_path: Path,
        budget_cny: float,
        config: LLMConfig = DEFAULT_LLM_CONFIG,
        completion_func: Any | None = None,
        sleep_func: Any = time.sleep,
        env_path: Path | None = None,
        global_ledger_path: Path | None = None,
        logger: JsonLogger | None = None,
        fail_on_retry_exhaustion: bool = False,
    ) -> None:
        # R091: production never calls the SDK in this process -- every request
        # goes to a worker that imported it itself. Importing it here too cost a
        # second full import (about 15 minutes on the R090 run host) for a value
        # used only as a mode flag.
        self._production = completion_func is None
        self._worker_pool = _ProviderWorkerPool()
        self.ledger_path = ledger_path
        self.global_ledger_path = global_ledger_path or project_root() / "data" / "runtime" / "llm_ledger.jsonl"
        self.budget_cny = budget_cny
        self.config = config
        self._completion = completion_func
        self._sleep = sleep_func
        self._env_path = env_path or project_root() / ".env"
        self._run_costs_cny: dict[str, float] = {}
        self._pending_costs_cny: dict[str, float] = {}
        self._cost_lock = threading.Lock()
        self._ledger_index_path = self.global_ledger_path.with_suffix(
            f"{self.global_ledger_path.suffix}.index.json"
        )
        self._ledger_cost_index, self._ledger_index_valid = self._load_ledger_cost_index()
        self.logger = logger or JsonLogger()
        self.fail_on_retry_exhaustion = fail_on_retry_exhaustion
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self.global_ledger_path.parent.mkdir(parents=True, exist_ok=True)

    def start_run(self, run_id: str) -> None:
        with self._cost_lock:
            self._run_costs_cny[run_id] = self._ledger_cost_for_run(run_id)
            self._pending_costs_cny.pop(run_id, None)

    def complete(
        self,
        *,
        role: str,
        messages: list[dict[str, str]],
        run_id: str,
        schema: type[SchemaT] | None = None,
        expected_cost_cny: float | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMCallResult:
        with self._cost_lock:
            if run_id not in self._run_costs_cny:
                self._run_costs_cny[run_id] = self._ledger_cost_for_run(run_id)
            current_cost = self._run_costs_cny[run_id]
            if current_cost >= self.budget_cny:
                raise BudgetExceededError(run_id, self.budget_cny, current_cost)
        role_config = self.config.roles.get(role)
        if not role_config:
            raise LLMClientError(f"No LLM model configured for role={role}")
        self._pricing_for_model(role_config.model)
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
        reservation_cny = expected_cost_cny or self._estimate_max_cost_cny(
            prompt_messages, role_config.model, role_config.max_completion_tokens
        )
        self._reserve_budget(run_id, reservation_cny)

        first_error: str | None = None
        first_error_kind: str | None = None
        try:
            with correlation_context(llm_call=role):
                raw_result = self._completion_with_retries(
                    role=role,
                    model=role_config.model,
                    fallback_model=role_config.fallback_model,
                    api_base=role_config.api_base,
                    api_key=api_key,
                    timeout_seconds=role_config.timeout_seconds or self.config.timeout_seconds,
                    max_completion_tokens=role_config.max_completion_tokens,
                    messages=prompt_messages,
                    tools=tools,
                )
        except BaseException:
            self._release_reservation(run_id, reservation_cny)
            raise
        content = raw_result.content
        parsed: BaseModel | None = None
        repair_attempts = 0
        if schema:
            try:
                parsed = self._parse_schema(content, schema)
            except StructuredOutputError as exc:
                first_error = str(exc)
                truncated = self._truncated(raw_result, role_config.max_completion_tokens)
                first_error_kind = "truncated" if truncated else exc.kind
                try:
                    self._record_ledger(
                        run_id=run_id,
                        role=role,
                        result=raw_result,
                        structured=True,
                        parse_error=first_error,
                        parse_error_kind=first_error_kind,
                    )
                finally:
                    self._release_reservation(run_id, reservation_cny)
                self._add_run_cost(run_id, raw_result.cost_cny)
                self._enforce_cost_overrun(
                    run_id,
                    expected_cost_cny,
                    raw_result.cost_cny,
                )
                if self.run_total_cny(run_id) > self.budget_cny:
                    raise BudgetExceededError(run_id, self.budget_cny, self.run_total_cny(run_id))
                if truncated:
                    # Repairing under an unchanged completion cap buys a second
                    # identical truncation.  Surface the cap instead.
                    raise StructuredOutputTruncatedError(
                        role=role,
                        completion_tokens=raw_result.completion_tokens,
                        max_completion_tokens=role_config.max_completion_tokens,
                        finish_reason=raw_result.finish_reason,
                    ) from exc
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
                reservation_cny = expected_cost_cny or self._estimate_max_cost_cny(
                    repair_messages, role_config.model, role_config.max_completion_tokens
                )
                self._reserve_budget(run_id, reservation_cny)
                try:
                    raw_result = self._completion_with_retries(
                        role=role,
                        model=role_config.model,
                        fallback_model=role_config.fallback_model,
                        api_base=role_config.api_base,
                        api_key=api_key,
                        timeout_seconds=role_config.timeout_seconds or self.config.timeout_seconds,
                        max_completion_tokens=role_config.max_completion_tokens,
                        messages=repair_messages,
                        tools=tools,
                        is_repair=True,
                    )
                except BaseException:
                    self._release_reservation(run_id, reservation_cny)
                    raise
                content = raw_result.content
                try:
                    parsed = self._parse_schema(content, schema)
                except BaseException as repair_exc:
                    # The repair request reached the provider and must be
                    # accounted for even when its response is invalid too.
                    repair_kind = first_error_kind
                    if self._truncated(raw_result, role_config.max_completion_tokens):
                        repair_kind = "truncated"
                    elif isinstance(repair_exc, StructuredOutputError):
                        repair_kind = repair_exc.kind
                    try:
                        self._record_ledger(
                            run_id=run_id,
                            role=role,
                            result=raw_result,
                            structured=True,
                            parse_error=first_error,
                            parse_error_kind=repair_kind,
                        )
                    finally:
                        self._release_reservation(run_id, reservation_cny)
                    self._add_run_cost(run_id, raw_result.cost_cny)
                    raise

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
            tool_calls=raw_result.tool_calls,
            finish_reason=raw_result.finish_reason,
        )
        try:
            self._record_ledger(
                run_id=run_id,
                role=role,
                result=result,
                structured=bool(schema),
                parse_error=first_error,
                parse_error_kind=first_error_kind,
            )
        finally:
            self._release_reservation(run_id, reservation_cny)
        self._add_run_cost(run_id, result.cost_cny)
        self._enforce_cost_overrun(
            run_id,
            expected_cost_cny,
            result.cost_cny,
        )
        if self.run_total_cny(run_id) > self.budget_cny:
            raise BudgetExceededError(run_id, self.budget_cny, self.run_total_cny(run_id))
        with correlation_context(llm_call=role):
            self.logger.event(
                "llm_call",
                model=result.model,
                total_tokens=result.total_tokens,
                cost_cny=result.cost_cny,
                latency_seconds=result.latency_seconds,
            )
        return result

    def complete_with_tools(
        self,
        *,
        role: str,
        messages: list[dict[str, str]],
        run_id: str,
        tools: list[dict[str, Any]],
        expected_cost_cny: float | None = None,
    ) -> LLMCallResult:
        """Request provider-native tool calls while retaining normal accounting."""
        return self.complete(
            role=role,
            messages=messages,
            run_id=run_id,
            expected_cost_cny=expected_cost_cny,
            tools=tools,
        )

    def run_total_cny(self, run_id: str) -> float:
        with self._cost_lock:
            if run_id not in self._run_costs_cny:
                self._run_costs_cny[run_id] = self._ledger_cost_for_run(run_id)
            return self._run_costs_cny[run_id]

    def reserve_external_call(self, *, run_id: str, estimated_cost_cny: float) -> None:
        """Reserve the existing run budget before a non-chat provider request.

        Embedding and rerank use provider-specific HTTP APIs, but their spend is
        deliberately governed by this same ledger and budget, not a parallel
        counter.  Callers must either settle or release every reservation.
        """
        if estimated_cost_cny < 0:
            raise ValueError("estimated_cost_cny must be non-negative")
        with self._cost_lock:
            if run_id not in self._run_costs_cny:
                self._run_costs_cny[run_id] = self._ledger_cost_for_run(run_id)
        self._reserve_budget(run_id, estimated_cost_cny)

    def release_external_call(self, *, run_id: str, estimated_cost_cny: float) -> None:
        self._release_reservation(run_id, estimated_cost_cny)

    def settle_external_call(
        self,
        *,
        run_id: str,
        role: str,
        call_kind: str,
        model: str,
        input_tokens: int,
        cost_cny: float,
        price_source: str,
        latency_seconds: float,
        estimated_cost_cny: float,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Append a non-chat provider call to the normal ledger and budget."""
        if call_kind not in {"embedding", "rerank"}:
            raise ValueError(f"unsupported external call_kind={call_kind}")
        if min(input_tokens, cost_cny, latency_seconds, estimated_cost_cny) < 0:
            raise ValueError("external call accounting values must be non-negative")
        row = {
            "run_id": run_id,
            "role": role,
            "call_kind": call_kind,
            "model": model,
            "prompt_tokens": input_tokens,
            "input_tokens": input_tokens,
            "prompt_cache_hit_tokens": 0,
            "prompt_cache_miss_tokens": input_tokens,
            "completion_tokens": 0,
            "output_tokens": 0,
            "total_tokens": input_tokens,
            "cost_usd": round(cost_cny * self.config.display_cny_to_usd_rate, 8),
            "cost_cny": round(cost_cny, 8),
            "price_source": price_source,
            "latency_seconds": round(latency_seconds, 3),
            "cache_hit": None,
            "structured": False,
            "repair_attempts": 0,
            "parse_error": False,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            **(metadata or {}),
        }
        try:
            self._append_ledger_row(row)
            self._add_run_cost(run_id, float(row["cost_cny"]))
            self._enforce_cost_overrun(run_id, estimated_cost_cny, float(row["cost_cny"]))
            if self.run_total_cny(run_id) > self.budget_cny:
                raise BudgetExceededError(run_id, self.budget_cny, self.run_total_cny(run_id))
        finally:
            self._release_reservation(run_id, estimated_cost_cny)

    def _add_run_cost(self, run_id: str, cost_cny: float) -> None:
        with self._cost_lock:
            self._run_costs_cny[run_id] = self._run_costs_cny.get(run_id, 0.0) + cost_cny

    def _reserve_budget(self, run_id: str, reservation_cny: float) -> None:
        with self._cost_lock:
            projected = (
                self._run_costs_cny[run_id]
                + self._pending_costs_cny.get(run_id, 0.0)
                + reservation_cny
            )
            if projected > self.budget_cny:
                raise BudgetExceededError(run_id, self.budget_cny, projected)
            self._pending_costs_cny[run_id] = (
                self._pending_costs_cny.get(run_id, 0.0) + reservation_cny
            )

    def _release_reservation(self, run_id: str, reservation_cny: float) -> None:
        with self._cost_lock:
            remaining = self._pending_costs_cny.get(run_id, 0.0) - reservation_cny
            if remaining > 1e-12:
                self._pending_costs_cny[run_id] = remaining
            else:
                self._pending_costs_cny.pop(run_id, None)

    def ledger_total_cny(self) -> float:
        total = 0.0
        for row in self._iter_ledger_rows(self.global_ledger_path):
            total += float(row.get("cost_cny", 0.0))
        return total

    def aggregate_run(self, run_id: str) -> dict[str, Any]:
        rows = [
            row for row in self._iter_ledger_rows(self.global_ledger_path) if row.get("run_id") == run_id
        ]
        price_sources = sorted(
            {
                str(row["price_source"])
                for row in rows
                if row.get("price_source")
            }
        )
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
                    "structured_calls": 0,
                    "structured_parse_errors": 0,
                    "truncated_calls": 0,
                },
            )
            bucket["calls"] = int(bucket["calls"]) + 1
            if row.get("structured"):
                bucket["structured_calls"] = int(bucket["structured_calls"]) + 1
                if row.get("parse_error"):
                    bucket["structured_parse_errors"] = (
                        int(bucket["structured_parse_errors"]) + 1
                    )
                if row.get("truncated"):
                    bucket["truncated_calls"] = int(bucket["truncated_calls"]) + 1
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
            "structured_output": {
                key: sum(int(bucket[key]) for bucket in by_role.values())
                for key in ("structured_calls", "structured_parse_errors", "truncated_calls")
            },
            "total_cost_cny": sum(float(r.get("cost_cny", 0.0)) for r in rows),
            "price_source": (
                price_sources[0]
                if len(price_sources) == 1
                else f"mixed:{','.join(price_sources)}"
                if price_sources
                else None
            ),
            "price_sources": price_sources,
        }

    def _completion_with_retries(
        self,
        *,
        role: str,
        model: str,
        fallback_model: str | None,
        api_base: str | None,
        api_key: str,
        timeout_seconds: int,
        max_completion_tokens: int,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
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
                    kwargs = dict(
                        model=candidate_model,
                        messages=messages,
                        temperature=self.config.temperature,
                        timeout=timeout_seconds,
                        max_tokens=max_completion_tokens,
                        api_key=api_key,
                        api_base=api_base,
                    )
                    if tools is not None:
                        kwargs["tools"] = tools
                    response = self._call_with_hard_timeout(
                        kwargs=kwargs,
                        timeout_seconds=timeout_seconds,
                    )
                    latency = time.perf_counter() - started
                    content = self._message_content(response)
                    usage = self._usage(response)
                    cost_cny, price_source = self._cost_cny(
                        usage,
                        candidate_model,
                    )
                    result = LLMCallResult(
                        content=content,
                        parsed=None,
                        model=candidate_model,
                        prompt_tokens=usage["prompt_tokens"],
                        prompt_cache_hit_tokens=usage["prompt_cache_hit_tokens"],
                        prompt_cache_miss_tokens=usage["prompt_cache_miss_tokens"],
                        completion_tokens=usage["completion_tokens"],
                        total_tokens=usage["total_tokens"],
                        # USD is display_only: the ledger's authoritative
                        # accounting amount and budget currency are CNY.
                        cost_usd=cost_cny * self.config.display_cny_to_usd_rate,
                        cost_cny=cost_cny,
                        price_source=price_source,
                        latency_seconds=latency,
                        cache_hit=self._cache_hit(response),
                        repair_attempts=1 if is_repair else 0,
                        tool_calls=self._message_tool_calls(response),
                        finish_reason=self._finish_reason(response),
                    )
                    recorder = active_trajectory_recorder()
                    if recorder:
                        recorder.record_llm_call(
                            LLMCallTrace(
                                role=role,
                                prompt=messages,
                                response=content,
                                prompt_tokens=result.prompt_tokens,
                                completion_tokens=result.completion_tokens,
                                total_tokens=result.total_tokens,
                                latency_seconds=result.latency_seconds,
                                model=result.model,
                                cost_usd=result.cost_usd,
                                cost_cny=result.cost_cny,
                                price_source=result.price_source,
                                cache_hit=result.cache_hit,
                                attempt=attempt + 1,
                                repair=is_repair,
                            )
                        )
                    return result
                except Exception as exc:  # litellm exceptions are provider-specific.
                    last_error = exc
                    recorder = active_trajectory_recorder()
                    if recorder:
                        recorder.record_llm_call(
                            LLMCallTrace(
                                role=role,
                                prompt=messages,
                                response="",
                                prompt_tokens=0,
                                completion_tokens=0,
                                total_tokens=0,
                                latency_seconds=max(0.0, time.perf_counter() - started),
                                model=candidate_model,
                                attempt=attempt + 1,
                                repair=is_repair,
                                error=type(exc).__name__,
                            )
                        )
                    if attempt >= self.config.max_retries:
                        break
                    self._sleep(2**attempt)
        raise LLMRetryExhaustedError(
            redact(f"LLM call failed for role={role}: {last_error}")
        )

    def _call_with_hard_timeout(
        self,
        *,
        kwargs: dict[str, Any],
        timeout_seconds: float,
    ) -> Any:
        """Bound an SDK call even when its transport timeout is ineffective.

        Production calls go to a per-thread worker process that has already
        imported the provider SDK; an overdue call still terminates that worker,
        which is then never reused.  On the main POSIX thread, an interval timer
        interrupts the synchronous SDK operation itself, so an SSL read cannot
        leave a provider worker alive after the deadline.  Python cannot safely
        interrupt an arbitrary non-main thread, so those callers use a bounded
        daemon-worker fallback.
        """
        if self._production:
            spawns_before = self._worker_pool.spawns
            response = self._worker_pool.call(kwargs, timeout_seconds)
            if self._worker_pool.spawns > spawns_before:
                self.logger.event(
                    "provider_worker_started",
                    **self._worker_pool.startup_records[-1],
                )
            return response
        assert self._completion is not None
        if (
            threading.current_thread() is threading.main_thread()
            and hasattr(signal, "setitimer")
        ):
            return self._call_with_main_thread_deadline(
                kwargs=kwargs,
                timeout_seconds=timeout_seconds,
            )
        return self._call_with_daemon_deadline(
            kwargs=kwargs,
            timeout_seconds=timeout_seconds,
        )

    @staticmethod
    def _call_litellm_in_subprocess(
        *,
        kwargs: dict[str, Any],
        timeout_seconds: float,
        worker_target: Callable[[dict[str, Any], Any], None] = _litellm_subprocess_worker,
    ) -> dict[str, Any]:
        """Terminate a stuck production SDK transport at its hard deadline."""
        context = multiprocessing.get_context("spawn")
        result_queue = context.Queue(maxsize=1)
        process = context.Process(
            target=worker_target,
            args=(kwargs, result_queue),
            daemon=True,
        )
        try:
            process.start()
            # Consume before joining: a large result can otherwise block the
            # child's queue feeder and make a successful request look timed out.
            try:
                status, payload = result_queue.get(timeout=timeout_seconds)
            except queue.Empty:
                status = payload = None
            if status is None:
                process.terminate()
                process.join(timeout=5)
                raise TimeoutError(
                    f"LLM operation timed out after {timeout_seconds:g}s; "
                    "provider subprocess terminated"
                )
            process.join(timeout=5)
            if status == "error":
                raise RuntimeError(str(payload))
            if not isinstance(payload, dict):
                raise RuntimeError("LiteLLM subprocess returned a non-object response")
            return payload
        finally:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
            result_queue.close()
            result_queue.join_thread()

    def _call_with_main_thread_deadline(
        self,
        *,
        kwargs: dict[str, Any],
        timeout_seconds: float,
    ) -> Any:
        def deadline_expired(_signum: int, _frame: Any) -> None:
            raise TimeoutError(f"LLM operation timed out after {timeout_seconds:g}s")

        previous_handler = signal.signal(signal.SIGALRM, deadline_expired)
        previous_delay, previous_interval = signal.setitimer(
            signal.ITIMER_REAL,
            timeout_seconds,
        )
        started = time.monotonic()
        try:
            return self._completion(**kwargs)
        finally:
            elapsed = time.monotonic() - started
            signal.setitimer(signal.ITIMER_REAL, 0.0)
            signal.signal(signal.SIGALRM, previous_handler)
            signal.setitimer(
                signal.ITIMER_REAL,
                max(0.0, previous_delay - elapsed),
                previous_interval,
            )

    def _call_with_daemon_deadline(
        self,
        *,
        kwargs: dict[str, Any],
        timeout_seconds: float,
    ) -> Any:
        if not _LLM_CALL_SLOTS.acquire(blocking=False):
            raise TimeoutError(
                "LLM detached-call capacity exhausted; refusing another provider call"
            )
        done = threading.Event()
        outcome: dict[str, Any] = {}

        def invoke() -> None:
            try:
                outcome["response"] = self._completion(**kwargs)
            except BaseException as exc:
                outcome["error"] = exc
            finally:
                _LLM_CALL_SLOTS.release()
                done.set()

        worker = threading.Thread(
            target=invoke,
            name="deepresearch-llm-call",
            daemon=True,
        )
        worker.start()
        if not done.wait(timeout_seconds):
            raise TimeoutError(
                f"LLM operation timed out after {timeout_seconds:g}s; "
                "detached worker quarantined"
            )
        if "error" in outcome:
            raise outcome["error"]
        return outcome["response"]

    def _api_key(self, key_name: str) -> str:
        env_value = os.getenv(key_name, "").strip()
        if env_value:
            return env_value
        if self._env_path.exists():
            for line in self._env_path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    continue
                key, value = stripped.split("=", 1)
                if key.strip() == key_name and value.strip():
                    return value.strip().strip('"').strip("'")
        raise LLMClientError(f"Missing {key_name} in .env or container environment.")

    def _parse_schema(self, content: str, schema: type[SchemaT]) -> SchemaT:
        try:
            return schema.model_validate_json(self._json_payload(content))
        except (ValidationError, ValueError, json.JSONDecodeError) as exc:
            error = StructuredOutputError(str(exc))
            error.kind = self._parse_error_kind(exc)
            raise error from exc

    @staticmethod
    def _parse_error_kind(exc: Exception) -> str:
        """Separate "not JSON" from "JSON that violates the schema".

        Pydantic reports a syntax error as a ``ValidationError`` too, so the
        exception type alone would file every malformed payload -- including a
        truncated one -- under ``schema_violation``.
        """

        if isinstance(exc, ValidationError):
            if any(str(error.get("type", "")).startswith("json_") for error in exc.errors()):
                return "invalid_json"
            return "schema_violation"
        return "invalid_json"

    @staticmethod
    def _truncated(result: LLMCallResult, max_completion_tokens: int) -> bool:
        """Distinguish "the model wrote bad JSON" from "we cut the model off".

        Both surface as an unparsable payload, and conflating them hid a
        permanently truncated extractor/reporter for fifteen rounds.
        """

        return (
            result.finish_reason == "length"
            or result.completion_tokens >= max_completion_tokens > 0
        )

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

    def _finish_reason(self, response: Any) -> str | None:
        choice = response["choices"][0] if isinstance(response, dict) else response.choices[0]
        value = (
            choice.get("finish_reason")
            if isinstance(choice, dict)
            else getattr(choice, "finish_reason", None)
        )
        return str(value) if value else None

    def _message_tool_calls(self, response: Any) -> tuple[dict[str, Any], ...]:
        choice = response["choices"][0] if isinstance(response, dict) else response.choices[0]
        message = choice["message"] if isinstance(choice, dict) else choice.message
        calls = message.get("tool_calls", []) if isinstance(message, dict) else getattr(message, "tool_calls", [])
        return tuple(
            item if isinstance(item, dict) else {
                "id": getattr(item, "id", None),
                "type": getattr(item, "type", None),
                "function": getattr(item, "function", None),
            }
            for item in (calls or [])
        )

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

    def _cost_cny(
        self,
        usage: dict[str, int],
        model: str,
    ) -> tuple[float, str]:
        tiers = self._pricing_for_model(model)
        pricing = next(
            (
                tier for tier in tiers
                if tier.max_prompt_tokens is None
                or usage["prompt_tokens"] <= tier.max_prompt_tokens
            ),
            None,
        )
        if pricing is None:
            raise LLMClientError(
                f"Prompt exceeds configured pricing tiers for model={model}"
            )
        miss_rate = getattr(
            pricing,
            "input_cache_miss_cny_per_million",
            self.config.input_cache_miss_cny_per_million,
        )
        hit_rate = getattr(
            pricing,
            "input_cache_hit_cny_per_million",
            self.config.input_cache_hit_cny_per_million,
        )
        output_rate = getattr(
            pricing,
            "output_cny_per_million",
            self.config.output_cny_per_million,
        )
        input_cost = (
            usage["prompt_cache_miss_tokens"] * miss_rate
            + usage["prompt_cache_hit_tokens"] * hit_rate
        )
        output_cost = usage["completion_tokens"] * output_rate
        return (
            (input_cost + output_cost) / 1_000_000,
            pricing.price_source,
        )

    def _pricing_for_model(self, model: str) -> tuple[Any, ...]:
        tiers = self.config.pricing_by_model.get(model, ())
        if not tiers:
            raise LLMClientError(f"No configured pricing for model={model}")
        return tiers

    def _estimate_max_cost_cny(
        self,
        messages: list[dict[str, str]],
        model: str,
        max_completion_tokens: int,
    ) -> float:
        # A conservative local token estimate is enough to reserve before a
        # paid call; the provider is also sent the same output cap.
        prompt_tokens = sum(max(1, len(item.get("content", "")) // 4) for item in messages)
        pricing = next(
            (
                tier
                for tier in self._pricing_for_model(model)
                if tier.max_prompt_tokens is None or prompt_tokens <= tier.max_prompt_tokens
            ),
            None,
        )
        if pricing is None:
            raise LLMClientError(f"Prompt exceeds configured pricing tiers for model={model}")
        return (
            prompt_tokens * pricing.input_cache_miss_cny_per_million
            + max_completion_tokens * pricing.output_cny_per_million
        ) / 1_000_000

    def _enforce_cost_overrun(
        self,
        run_id: str,
        estimated_cny: float | None,
        actual_cny: float,
    ) -> None:
        if estimated_cny is None:
            return
        if estimated_cny < 0:
            raise ValueError("expected_cost_cny must be non-negative")
        if actual_cny > estimated_cny * 2:
            raise CostOverrunError(run_id, estimated_cny, actual_cny)

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
        parse_error_kind: str | None = None,
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
            "parse_error_kind": parse_error_kind,
            "finish_reason": result.finish_reason,
            "truncated": parse_error_kind == "truncated",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        self._append_ledger_row(row)

    def _append_ledger_row(self, row: dict[str, Any]) -> None:
        encoded = json.dumps(row, ensure_ascii=False) + "\n"
        ledger_paths = [self.global_ledger_path]
        if self.ledger_path.resolve() != self.global_ledger_path.resolve():
            ledger_paths.append(self.ledger_path)
        for path in ledger_paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as file:
                file.write(encoded)
        self._update_ledger_cost_index(str(row["run_id"]), float(row["cost_cny"]))

    def _ledger_cost_for_run(self, run_id: str) -> float:
        if not self._ledger_index_valid:
            self._ledger_cost_index = self._rebuild_ledger_cost_index()
            self._ledger_index_valid = True
            self._save_ledger_cost_index()
        return self._ledger_cost_index.get(run_id, 0.0)

    def _load_ledger_cost_index(self) -> tuple[dict[str, float], bool]:
        if not self._ledger_index_path.exists():
            return {}, not self.global_ledger_path.exists()
        try:
            payload = json.loads(self._ledger_index_path.read_text(encoding="utf-8"))
            ledger_stat = self.global_ledger_path.stat()
            if (
                payload.get("ledger_size") != ledger_stat.st_size
                or payload.get("ledger_mtime_ns") != ledger_stat.st_mtime_ns
            ):
                return {}, False
            return {
                str(run_id): float(cost)
                for run_id, cost in dict(payload.get("costs", {})).items()
            }, True
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return {}, False

    def _rebuild_ledger_cost_index(self) -> dict[str, float]:
        costs: dict[str, float] = {}
        if not self.global_ledger_path.exists():
            return costs
        with self.global_ledger_path.open(encoding="utf-8") as file:
            for line in file:
                try:
                    row = json.loads(line)
                    run_id = str(row["run_id"])
                    costs[run_id] = costs.get(run_id, 0.0) + float(row.get("cost_cny", 0.0))
                except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                    continue
        return costs

    def _update_ledger_cost_index(self, run_id: str, cost_cny: float) -> None:
        with self._cost_lock:
            if not self._ledger_index_valid:
                self._ledger_cost_index = self._rebuild_ledger_cost_index()
                self._ledger_index_valid = True
            else:
                self._ledger_cost_index[run_id] = self._ledger_cost_index.get(run_id, 0.0) + cost_cny
            self._save_ledger_cost_index()

    def _save_ledger_cost_index(self) -> None:
        ledger_stat = self.global_ledger_path.stat()
        payload = {
            "ledger_size": ledger_stat.st_size,
            "ledger_mtime_ns": ledger_stat.st_mtime_ns,
            "costs": self._ledger_cost_index,
        }
        temporary_path = self._ledger_index_path.with_suffix(".tmp")
        temporary_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        temporary_path.replace(self._ledger_index_path)

    def _ledger_cost_for_run_legacy(self, run_id: str) -> float:
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

    @staticmethod
    def _load_litellm() -> Any:
        """Import the provider SDK in this process.

        Production no longer uses this: the worker imports the SDK itself. Kept
        as the explicit way to check availability without guessing at a module
        name, and used by the worker-startup failure path's error text.
        """

        try:
            return import_module("litellm")
        except ModuleNotFoundError as exc:  # pragma: no cover - exercised only in misconfigured envs.
            raise LLMClientError("litellm is not installed.") from exc
