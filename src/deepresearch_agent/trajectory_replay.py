from __future__ import annotations

import os
from collections import defaultdict, deque
from dataclasses import replace
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from deepresearch_agent.schemas import (
    ResearchPlan,
    Source,
    StructuredDataRecord,
    SymbolInfo,
)
from deepresearch_agent.settings import load_settings
from deepresearch_agent.trajectory import (
    AgentTrajectory,
    ReplayResult,
    ToolCallTrace,
    active_trajectory_recorder,
)
from deepresearch_agent.workflow import DeepResearchEngine


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
            if name == "web_fetch" and not call.error:
                self._fetches[str(call.inputs["url"])].append(call)
            if name != "web_search" or call.error:
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

    request = trajectory.request
    if request.get("mode") != "deterministic":
        return ReplayResult(
            mode=mode,
            status="cache_miss",
            cache_miss="real-mode replay is deferred until a real trajectory is recorded",
        )
    os.environ["DEEPRESEARCH_MODE"] = "deterministic"
    os.environ["DEEPRESEARCH_SEARCH_PROVIDER"] = "fixture"
    os.environ["DEEPRESEARCH_STRUCTURED_DATA_PROVIDER"] = "fixture"
    if request.get("as_of"):
        os.environ["DEEPRESEARCH_AS_OF"] = str(request["as_of"])

    with TemporaryDirectory(prefix="trajectory-replay-") as temp_dir:
        root = Path(temp_dir)
        settings = replace(
            load_settings(),
            storage_path=root / "replay.db",
            runs_root=root / "runs",
            execution_mode="deterministic",
            run_manifest_enabled=False,
            structured_logging_enabled=False,
            trajectory_record_enabled=False,
            tool_contract_enabled=False,
            **{
                key: value
                for key, value in request.get(
                    "strategy_config",
                    {},
                ).items()
                if key
                in {
                    "max_critic_iter",
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
            },
        )
        engine = DeepResearchEngine(
            settings=settings,
            search_tool=ReplaySearchProvider(trajectory),
            structured_data_provider=ReplayStructuredDataProvider(
                trajectory
            ),
        )
        if isinstance(request.get("recorded_plan"), dict):
            engine.planner = ReplayPlanner(
                ResearchPlan.model_validate(request["recorded_plan"])
            )
        try:
            state = engine.run(
                topic=str(request["topic"]),
                depth_level=int(request["depth_level"]),
            )
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

    actual = {"report.md": state.final_report or ""}
    matches = {
        name: actual.get(name) == content
        for name, content in trajectory.artifacts.items()
    }
    mismatch = next(
        (
            _mismatch_summary(
                trajectory.artifacts[name],
                actual.get(name, ""),
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
