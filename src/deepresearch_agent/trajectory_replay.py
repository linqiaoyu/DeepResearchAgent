from __future__ import annotations

import json
import time
from collections import defaultdict, deque
from dataclasses import replace
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from pydantic import BaseModel, ValidationError

from deepresearch_agent.llm import (
    LLMCallResult,
    LLMClientError,
    StructuredOutputError,
)
from deepresearch_agent.schemas import (
    ResearchPlan,
    ResearchState,
    Source,
    StructuredDataRecord,
    SymbolInfo,
)
from deepresearch_agent.settings import Settings
from deepresearch_agent.trajectory import (
    AgentTrajectory,
    LLMCallTrace,
    ReplayResult,
    ToolCallTrace,
    active_trajectory_recorder,
    normalized_llm_key,
    validate_strict_replay_trajectory,
)
from deepresearch_agent.workflow import DeepResearchEngine
from langgraph.graph import START


class ReplayLLMClient:
    """Exact, offline LLM boundary backed only by recorded call traces."""

    def __init__(self, trajectory: AgentTrajectory) -> None:
        self._expected_run_id = trajectory.run_id
        self._calls: deque[LLMCallTrace] = deque(
            sorted(
                trajectory.llm_calls,
                key=lambda item: item.sequence or 0,
            )
        )
        self._consumed: list[LLMCallTrace] = []

    def start_run(self, run_id: str) -> None:
        self._require_run_id(run_id)

    def complete(
        self,
        *,
        role: str,
        messages: list[dict[str, str]],
        run_id: str,
        schema: type[BaseModel] | None = None,
        expected_cost_cny: float | None = None,
    ) -> LLMCallResult:
        del expected_cost_cny
        self._require_run_id(run_id)
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
        call = self._consume_success(
            role=role,
            prompt=prompt_messages,
            repair=False,
        )
        parsed: BaseModel | None = None
        repair_attempts = 0
        if schema:
            try:
                parsed = schema.model_validate_json(
                    _json_payload(call.response)
                )
            except (ValidationError, ValueError, json.JSONDecodeError) as exc:
                first_error = str(exc)
                repair_messages = [
                    *prompt_messages,
                    {"role": "assistant", "content": call.response},
                    {
                        "role": "user",
                        "content": (
                            "The previous JSON failed validation. Correct it and "
                            "return only valid JSON. "
                            f"Validation error: {first_error}"
                        ),
                    },
                ]
                call = self._consume_success(
                    role=role,
                    prompt=repair_messages,
                    repair=True,
                )
                repair_attempts = 1
                try:
                    parsed = schema.model_validate_json(
                        _json_payload(call.response)
                    )
                except (
                    ValidationError,
                    ValueError,
                    json.JSONDecodeError,
                ) as repair_exc:
                    raise StructuredOutputError(str(repair_exc)) from repair_exc
        return _llm_result(call, parsed=parsed, repair_attempts=repair_attempts)

    def run_total_cny(self, run_id: str) -> float:
        self._require_run_id(run_id)
        return sum(
            call.cost_cny for call in self._consumed if not call.error
        )

    def ledger_total_cny(self) -> float:
        return sum(
            call.cost_cny for call in self._consumed if not call.error
        )

    def aggregate_run(self, run_id: str) -> dict[str, object]:
        self._require_run_id(run_id)
        rows = [
            _llm_ledger_row(run_id, call)
            for call in self._consumed
            if not call.error
        ]
        by_role: dict[str, dict[str, float | int]] = {}
        for row in rows:
            role = str(row["role"])
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
                bucket[key] = int(bucket[key]) + int(row[key])
            for key in ("cost_usd", "cost_cny", "latency_seconds"):
                bucket[key] = float(bucket[key]) + float(row[key])
        return {
            "rows": rows,
            "by_role": by_role,
            "total_cost_cny": sum(float(row["cost_cny"]) for row in rows),
            "price_source": "trajectory",
        }

    def assert_exhausted(self) -> None:
        if self._calls:
            call = self._calls[0]
            raise RuntimeError(
                "trajectory cache_miss: unused LLM call "
                f"role={call.role!r} sequence={call.sequence}"
            )

    def _consume_success(
        self,
        *,
        role: str,
        prompt: list[dict[str, str]],
        repair: bool,
    ) -> LLMCallTrace:
        expected_key = normalized_llm_key(role=role, prompt=prompt)
        consumed_error: LLMCallTrace | None = None
        while self._calls:
            call = self._calls[0]
            prompt_matches = (
                call.normalized_key == expected_key
                or _matches_after_retry_task_id_normalization(
                    role=role,
                    recorded=call.prompt,
                    actual=prompt,
                )
            )
            if (
                call.role != role
                or not prompt_matches
                or call.repair != repair
            ):
                if consumed_error is not None:
                    raise LLMClientError(
                        "trajectory recorded LLM failure "
                        f"role={role} error={consumed_error.error}"
                    )
                prompt_diff = _mismatch_summary(
                    json.dumps(
                        call.prompt,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    json.dumps(
                        prompt,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    f"llm:{role}:prompt",
                )
                raise RuntimeError(
                    "trajectory cache_miss: LLM exact prompt mismatch "
                    f"role={role!r} sequence={call.sequence}; "
                    f"{prompt_diff}"
                )
            call = self._calls.popleft()
            self._consumed.append(call)
            if call.error:
                consumed_error = call
                continue
            return call
        if consumed_error is not None:
            raise LLMClientError(
                "trajectory recorded LLM failure "
                f"role={role} error={consumed_error.error}"
            )
        raise RuntimeError(
            f"trajectory cache_miss: LLM role={role!r}"
        )

    def _require_run_id(self, run_id: str) -> None:
        if run_id != self._expected_run_id:
            raise RuntimeError(
                "trajectory cache_miss: replay run_id differs "
                f"expected={self._expected_run_id!r} actual={run_id!r}"
            )


class ReplaySearchProvider:
    def __init__(self, trajectory: AgentTrajectory) -> None:
        self._responses: dict[
            tuple[str, int, str | None],
            deque[ToolCallTrace],
        ] = defaultdict(deque)
        self._fetches: dict[str, deque[ToolCallTrace]] = defaultdict(
            deque
        )
        for call in trajectory.tool_calls:
            name = call.tool_spec.get("name")
            if name == "web_fetch":
                self._fetches[str(call.inputs["url"])].append(call)
            if name != "web_search":
                continue
            key = (
                str(call.inputs["query"]),
                int(call.inputs.get("top_k", 3)),
                call.inputs.get("source_type"),
            )
            self._responses[key].append(call)

    def search(
        self,
        query: str,
        top_k: int = 3,
        source_type: str | None = None,
    ) -> list[Source]:
        key = (query, top_k, source_type)
        queue = self._responses.get(key)
        if not queue:
            raise RuntimeError(f"trajectory cache_miss: web_search {key!r}")
        call = queue.popleft()
        recorder = active_trajectory_recorder()
        if recorder:
            recorder.record_tool_call(call.model_copy(deep=True))
        return [
            Source.model_validate(item)
            for item in (call.result or [])
        ]

    def fetch(self, url: str) -> Source | None:
        queue = self._fetches.get(url)
        if not queue:
            raise RuntimeError(
                f"trajectory cache_miss: web_fetch {url!r}"
            )
        call = queue.popleft()
        recorder = active_trajectory_recorder()
        if recorder:
            recorder.record_tool_call(call.model_copy(deep=True))
        return (
            Source.model_validate(call.result)
            if call.result
            else None
        )

    def assert_exhausted(self) -> None:
        remaining = [
            call
            for queue in (*self._responses.values(), *self._fetches.values())
            for call in queue
        ]
        if remaining:
            call = min(remaining, key=lambda item: item.sequence or 0)
            raise RuntimeError(
                "trajectory cache_miss: unused tool call "
                f"tool={call.tool_spec.get('name')!r} "
                f"sequence={call.sequence}"
            )


class ReplayStructuredDataProvider:
    def __init__(self, trajectory: AgentTrajectory) -> None:
        self._calls = deque(
            call
            for call in trajectory.tool_calls
            if call.tool_spec.get("name")
            == "structured_data_provider"
        )

    def symbol_resolve(self, company_name: str) -> SymbolInfo | None:
        call = self._next(
            "symbol_resolve",
            {"company_name": company_name},
        )
        return (
            SymbolInfo.model_validate(call.result)
            if call.result
            else None
        )

    def financial_indicators(
        self,
        symbol: str,
        periods: list[str] | None = None,
        metrics: list[str] | None = None,
    ) -> list[StructuredDataRecord]:
        call = self._next(
            "financial_indicators",
            {
                "symbol": symbol,
                "periods": periods,
                "metrics": metrics,
            },
        )
        return [
            StructuredDataRecord.model_validate(item)
            for item in (call.result or [])
        ]

    def price_history(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> list[StructuredDataRecord]:
        call = self._next(
            "price_history",
            {
                "symbol": symbol,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            },
        )
        return [
            StructuredDataRecord.model_validate(item)
            for item in (call.result or [])
        ]

    def _next(self, operation: str, expected: dict[str, object]):
        if not self._calls:
            raise RuntimeError(
                "trajectory cache_miss: structured_data_provider "
                f"{operation}"
            )
        call = self._calls.popleft()
        actual_operation = call.inputs.get("operation")
        if actual_operation != operation or any(
            call.inputs.get(key) != value
            for key, value in expected.items()
        ):
            raise RuntimeError(
                "trajectory cache_miss: structured_data_provider "
                f"expected={operation}/{expected}, actual={call.inputs}"
            )
        if call.error:
            raise RuntimeError(
                "trajectory recorded structured provider error: "
                f"{call.error}"
            )
        return call

    def assert_exhausted(self) -> None:
        if self._calls:
            call = self._calls[0]
            raise RuntimeError(
                "trajectory cache_miss: unused tool call "
                "tool='structured_data_provider' "
                f"sequence={call.sequence}"
            )


class ReplayDisclosureSource:
    """Offline disclosure backend with exact FIFO input matching."""

    def __init__(self, trajectory: AgentTrajectory) -> None:
        self._calls: deque[ToolCallTrace] = deque(
            sorted(
                (
                    call
                    for call in trajectory.tool_calls
                    if call.tool_spec.get("name") == "disclosure_source"
                ),
                key=lambda item: item.sequence or 0,
            )
        )

    def set_run_context(self, context: object) -> None:
        del context

    def search(
        self,
        security_code: str,
        keyword: str,
        start_date: date,
        end_date: date,
        *,
        preferred_terms: tuple[str, ...] = (),
    ) -> list[Source]:
        del preferred_terms
        expected = {
            "security_code": security_code,
            "keyword": keyword,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        }
        if not self._calls:
            raise RuntimeError(
                "trajectory cache_miss: disclosure_source "
                f"{expected!r}"
            )
        call = self._calls.popleft()
        if call.inputs != expected:
            raise RuntimeError(
                "trajectory cache_miss: disclosure_source "
                f"expected={expected}, actual={call.inputs}"
            )
        if call.error:
            raise RuntimeError(
                "trajectory recorded disclosure_source error: "
                f"{call.error}"
            )
        return [
            Source.model_validate(item)
            for item in (call.result or [])
        ]

    def assert_exhausted(self) -> None:
        if self._calls:
            call = self._calls[0]
            raise RuntimeError(
                "trajectory cache_miss: unused tool call "
                "tool='disclosure_source' "
                f"sequence={call.sequence}"
            )


class ReplayPlanner:
    def __init__(self, plan: ResearchPlan) -> None:
        self._plan = plan
        self.last_stats: dict[str, object] = {}

    def plan(
        self,
        topic: str,
        depth_level: int = 2,
        research_id: str | None = None,
    ) -> ResearchPlan:
        if (
            topic != self._plan.topic
            or depth_level != self._plan.depth_level
        ):
            raise RuntimeError(
                "trajectory cache_miss: recorded plan request differs"
            )
        return self._plan.model_copy(deep=True)


class ReplayPlannerGuard:
    """Validate the real-mode planner result before later loop refinements."""

    def __init__(self, planner: object, plan: ResearchPlan) -> None:
        self._planner = planner
        self._plan = plan

    @property
    def last_stats(self) -> object:
        return getattr(self._planner, "last_stats", {})

    def plan(
        self,
        topic: str,
        depth_level: int = 2,
        research_id: str | None = None,
    ) -> ResearchPlan:
        planner_call = getattr(self._planner, "plan")
        actual = planner_call(
            topic,
            depth_level,
            research_id=research_id,
        )
        if actual.model_dump(mode="json") != self._plan.model_dump(
            mode="json"
        ):
            raise RuntimeError(
                "trajectory cache_miss: replayed ResearchPlan differs "
                "from recorded_plan"
            )
        return actual


def replay_trajectory(
    trajectory: AgentTrajectory,
    *,
    mode: str,
    required_calls: list[str] | None = None,
) -> ReplayResult:
    if mode != "strict":
        raise ValueError(
            "strategy replay is not implemented; use strict replay"
        )
    available = {
        *(f"tool:{call.tool_spec.get('name')}" for call in trajectory.tool_calls),
        *(f"llm:{call.role}" for call in trajectory.llm_calls),
    }
    for required in required_calls or []:
        if required not in available:
            return ReplayResult(
                mode=mode,
                status="cache_miss",
                cache_miss=required,
            )

    validate_strict_replay_trajectory(trajectory)

    request = trajectory.request
    if (
        trajectory.schema_version == 4
        and trajectory.termination
        and trajectory.termination.status != "completed"
    ):
        return ReplayResult(
            mode=mode,
            status="cache_miss",
            cache_miss=(
                "trajectory terminal status is not replayable: "
                f"{trajectory.termination.status}"
            ),
        )
    recorded_mode = str(request.get("mode"))
    if recorded_mode not in {"deterministic", "llm"}:
        return ReplayResult(
            mode=mode,
            status="cache_miss",
            cache_miss=f"unsupported recorded mode: {recorded_mode!r}",
        )
    supported_tools = {
        "web_search",
        "web_fetch",
        "structured_data_provider",
        "disclosure_source",
    }
    unsupported = sorted(
        {
            str(call.tool_spec.get("name"))
            for call in trajectory.tool_calls
            if call.tool_spec.get("name") not in supported_tools
        }
    )
    if recorded_mode == "llm" and unsupported:
        return ReplayResult(
            mode=mode,
            status="cache_miss",
            cache_miss=(
                "unsupported recorded tool call(s): "
                + ", ".join(unsupported)
            ),
        )

    with TemporaryDirectory(prefix="trajectory-replay-") as temp_dir:
        root = Path(temp_dir)
        settings = _offline_settings(
            root=root,
            request=request,
        )
        replay_search = ReplaySearchProvider(trajectory)
        replay_structured = ReplayStructuredDataProvider(trajectory)
        replay_disclosure = ReplayDisclosureSource(trajectory)
        replay_llm = ReplayLLMClient(trajectory)
        has_disclosure_trace = any(
            call.tool_spec.get("name") == "disclosure_source"
            for call in trajectory.tool_calls
        )
        engine = DeepResearchEngine(
            settings=settings,
            search_tool=replay_search,
            structured_data_provider=replay_structured,
            disclosure_source=(
                replay_disclosure
                if recorded_mode == "llm" or has_disclosure_trace
                else None
            ),
        )
        if recorded_mode == "deterministic":
            engine.planner = ReplayPlanner(
                ResearchPlan.model_validate(request["recorded_plan"])
            )
        else:
            engine.settings = replace(
                settings,
                execution_mode="llm",
            )
            engine.llm_client = replay_llm
            engine.planner.llm_client = replay_llm
            engine.planner.settings = engine.settings
            engine.planner = ReplayPlannerGuard(
                engine.planner,
                ResearchPlan.model_validate(request["recorded_plan"]),
            )
            engine.extractor.llm_client = replay_llm
            engine.reporter.llm_client = replay_llm
        try:
            state = _run_with_recorded_id(
                engine,
                trajectory=trajectory,
            )
            boundaries: list[object] = [
                replay_search,
                replay_structured,
                replay_disclosure,
            ]
            if recorded_mode == "llm":
                boundaries.append(replay_llm)
            for boundary in boundaries:
                boundary.assert_exhausted()
        except RuntimeError as exc:
            if "cache_miss" in str(exc):
                return ReplayResult(
                    mode=mode,
                    status="cache_miss",
                    cache_miss=str(exc),
                )
            raise
        finally:
            engine._checkpoint_conn.close()

    actual: dict[str, str] = {}
    for name in trajectory.artifacts:
        if name == "report.md":
            actual[name] = state.final_report or ""
            continue
        return ReplayResult(
            mode=mode,
            status="cache_miss",
            cache_miss=f"unsupported replay artifact: {name}",
        )
    matches = {
        name: actual[name] == content
        for name, content in trajectory.artifacts.items()
    }
    mismatch = next(
        (
            _mismatch_summary(
                trajectory.artifacts[name],
                actual[name],
                name,
            )
            for name, matches_artifact in matches.items()
            if not matches_artifact
        ),
        None,
    )
    return ReplayResult(
        mode=mode,
        status="reproduced" if all(matches.values()) else "mismatch",
        cache_miss=mismatch,
        artifact_matches=matches,
    )


_STRATEGY_SETTING_KEYS = {
    "max_critic_iter",
    "max_external_search_requests_per_run",
    "max_external_fetch_requests_per_run",
    "max_authority_search_requests_per_run",
    "max_authority_fetch_requests_per_run",
    "branch_budget_enabled",
    "branch_total_budget",
    "branch_single_cap",
    "research_loop_enabled",
    "research_loop_max_iterations",
    "research_loop_budget_ceiling",
    "research_loop_no_progress_window",
    "research_min_evidence_count",
    "research_min_independent_domains",
    "research_min_average_confidence",
    "research_max_freshness_age_days",
    "research_max_unresolved_critic_issues",
    "decision_weaving_enabled",
    "decision_weaving_budget_remaining_ratio",
    "decision_weaving_verify_min_allocation",
    "numeric_check_enabled",
    "numeric_check_relative_tolerance",
    "numeric_check_absolute_tolerance",
    "dynamic_capability_enabled",
    "dynamic_capability_rules_json",
    "reflection_enabled",
    "skill_packs_enabled",
}


def _offline_settings(
    *,
    root: Path,
    request: dict[str, object],
) -> Settings:
    as_of_value = request.get("as_of")
    as_of = (
        date.fromisoformat(str(as_of_value))
        if as_of_value
        else None
    )
    base = Settings(
        storage_path=root / "replay.db",
        runs_root=root / "runs",
        llm_ledger_path=root / "llm-ledger.jsonl",
        as_of=as_of,
        execution_mode="deterministic",
        run_manifest_enabled=False,
        structured_logging_enabled=False,
        config_fail_fast_enabled=False,
        trajectory_record_enabled=False,
        tool_contract_enabled=False,
    )
    strategy = request.get("strategy_config", {})
    if not isinstance(strategy, dict):
        raise ValueError("trajectory strategy_config must be an object")
    known_fields = set(Settings.__dataclass_fields__)
    values = {
        key: value
        for key, value in strategy.items()
        if key in _STRATEGY_SETTING_KEYS and key in known_fields
    }
    return replace(base, **values)


def _run_with_recorded_id(
    engine: DeepResearchEngine,
    *,
    trajectory: AgentTrajectory,
) -> ResearchState:
    request = trajectory.request
    state = ResearchState(
        research_id=trajectory.run_id,
        topic=str(request["topic"]),
        depth_level=int(request["depth_level"]),
    )
    state.metadata["execution_mode"] = engine.settings.execution_mode
    config = engine._config(trajectory.run_id)
    engine.graph.update_state(
        config,
        {
            "research_state": engine._dump_state(state),
            "started_at": time.perf_counter(),
            "stop_after_phase": None,
        },
        as_node=START,
    )
    replayed = engine.run(
        research_id=trajectory.run_id,
        resume=True,
    )
    if replayed.research_id != trajectory.run_id:
        raise RuntimeError(
            "trajectory cache_miss: replay failed to preserve run_id"
        )
    return replayed


def _json_payload(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _matches_after_retry_task_id_normalization(
    *,
    role: str,
    recorded: list[dict[str, str]],
    actual: list[dict[str, str]],
) -> bool:
    """Permit only Critic-generated opaque retry IDs to differ.

    ``RetryTask`` currently defaults to UUID4, so a byte-identical real replay
    can regenerate a different identifier even when every decision-bearing
    field is identical.  The exception is deliberately reporter-only and
    path-specific; evidence IDs and all other prompt content remain exact.
    """

    if role != "reporter" or len(recorded) != len(actual):
        return False
    return _normalize_reporter_retry_ids(recorded) == (
        _normalize_reporter_retry_ids(actual)
    )


def _normalize_reporter_retry_ids(
    prompt: list[dict[str, str]],
) -> list[dict[str, str]]:
    normalized = [dict(item) for item in prompt]
    for message in normalized:
        if message.get("role") != "user":
            continue
        try:
            payload = json.loads(message.get("content", ""))
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        critic = payload.get("critic_report")
        if not isinstance(critic, dict):
            continue
        for issue in critic.get("issues", []):
            if not isinstance(issue, dict):
                continue
            task = issue.get("suggested_retry_task")
            if isinstance(task, dict) and "id" in task:
                task["id"] = "[RETRY_TASK_ID]"
        for task in critic.get("retry_tasks", []):
            if isinstance(task, dict) and "id" in task:
                task["id"] = "[RETRY_TASK_ID]"
        message["content"] = json.dumps(
            payload,
            ensure_ascii=False,
        )
    return normalized


def _llm_result(
    call: LLMCallTrace,
    *,
    parsed: BaseModel | None,
    repair_attempts: int,
) -> LLMCallResult:
    cache_hit_tokens = call.prompt_tokens if call.cache_hit else 0
    return LLMCallResult(
        content=call.response,
        parsed=parsed,
        model=call.model,
        prompt_tokens=call.prompt_tokens,
        prompt_cache_hit_tokens=cache_hit_tokens,
        prompt_cache_miss_tokens=call.prompt_tokens - cache_hit_tokens,
        completion_tokens=call.completion_tokens,
        total_tokens=call.total_tokens,
        cost_usd=call.cost_usd,
        cost_cny=call.cost_cny,
        price_source=call.price_source or "trajectory",
        latency_seconds=call.latency_seconds,
        cache_hit=call.cache_hit,
        repair_attempts=repair_attempts,
    )


def _llm_ledger_row(
    run_id: str,
    call: LLMCallTrace,
) -> dict[str, object]:
    cache_hit_tokens = call.prompt_tokens if call.cache_hit else 0
    return {
        "run_id": run_id,
        "role": call.role,
        "model": call.model,
        "prompt_tokens": call.prompt_tokens,
        "prompt_cache_hit_tokens": cache_hit_tokens,
        "prompt_cache_miss_tokens": (
            call.prompt_tokens - cache_hit_tokens
        ),
        "completion_tokens": call.completion_tokens,
        "total_tokens": call.total_tokens,
        "cost_usd": call.cost_usd,
        "cost_cny": call.cost_cny,
        "latency_seconds": call.latency_seconds,
    }


def _mismatch_summary(expected: str, actual: str, name: str) -> str:
    limit = min(len(expected), len(actual))
    index = next(
        (
            item
            for item in range(limit)
            if expected[item] != actual[item]
        ),
        limit,
    )
    return (
        f"artifact mismatch {name} at char {index}: "
        f"expected={expected[max(0, index - 180):index + 120]!r}, "
        f"actual={actual[max(0, index - 180):index + 120]!r}"
    )
