from __future__ import annotations

import os
from collections import defaultdict, deque
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from deepresearch_agent.schemas import Source
from deepresearch_agent.settings import load_settings
from deepresearch_agent.tools import build_structured_data_provider
from deepresearch_agent.trajectory import AgentTrajectory, ReplayResult
from deepresearch_agent.workflow import DeepResearchEngine


class ReplaySearchProvider:
    def __init__(self, trajectory: AgentTrajectory) -> None:
        self._responses: dict[
            tuple[str, int, str | None],
            deque[list[Source]],
        ] = defaultdict(deque)
        for call in trajectory.tool_calls:
            if call.tool_spec.get("name") != "web_search" or call.error:
                continue
            key = (
                str(call.inputs["query"]),
                int(call.inputs.get("top_k", 3)),
                call.inputs.get("source_type"),
            )
            self._responses[key].append(
                [Source.model_validate(item) for item in (call.result or [])]
            )

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
        return queue.popleft()

    def fetch(self, url: str) -> Source | None:
        return None


def replay_trajectory(
    trajectory: AgentTrajectory,
    *,
    mode: str,
    required_calls: list[str] | None = None,
) -> ReplayResult:
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
        )
        engine = DeepResearchEngine(
            settings=settings,
            search_tool=ReplaySearchProvider(trajectory),
            structured_data_provider=build_structured_data_provider(),
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
    return ReplayResult(
        mode=mode,
        status="reproduced" if all(matches.values()) else "mismatch",
        artifact_matches=matches,
    )
