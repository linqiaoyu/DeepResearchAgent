from __future__ import annotations

import json
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Literal

from pydantic import Field

from deepresearch_agent.schemas import AgentDecision, StrictModel, utc_now
from deepresearch_agent.security import redact


class LLMCallTrace(StrictModel):
    role: str
    prompt: list[dict[str, str]]
    response: str
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    latency_seconds: float = Field(ge=0)
    model: str
    attempt: int = Field(ge=1)
    repair: bool = False
    error: str | None = None


class ToolCallTrace(StrictModel):
    tool_spec: dict[str, Any]
    inputs: dict[str, Any]
    result: Any = None
    error: dict[str, Any] | None = None
    attempts: int = Field(ge=0)


class NodeTransitionTrace(StrictModel):
    node: str
    input_summary: dict[str, Any]
    output_summary: dict[str, Any]


class AgentTrajectory(StrictModel):
    schema_version: int = 1
    run_id: str
    recorded_at: datetime = Field(default_factory=utc_now)
    request: dict[str, Any]
    llm_calls: list[LLMCallTrace] = Field(default_factory=list)
    tool_calls: list[ToolCallTrace] = Field(default_factory=list)
    node_transitions: list[NodeTransitionTrace] = Field(default_factory=list)
    agent_decisions: list[AgentDecision] = Field(default_factory=list)
    run_manifest_ref: str | None = None
    artifacts: dict[str, str] = Field(default_factory=dict)


class ReplayResult(StrictModel):
    mode: Literal["strict", "strategy"]
    status: Literal["reproduced", "cache_miss", "mismatch"]
    cache_miss: str | None = None
    artifact_matches: dict[str, bool] = Field(default_factory=dict)


class TrajectoryRecorder:
    def __init__(self, *, run_id: str, request: dict[str, Any]) -> None:
        self.trajectory = AgentTrajectory(run_id=run_id, request=request)

    def record_llm_call(self, call: LLMCallTrace) -> None:
        self.trajectory.llm_calls.append(call)

    def record_tool_call(self, call: ToolCallTrace) -> None:
        self.trajectory.tool_calls.append(call)

    def record_node_transition(self, transition: NodeTransitionTrace) -> None:
        self.trajectory.node_transitions.append(transition)

    def record_decision(self, decision: AgentDecision) -> None:
        self.trajectory.agent_decisions.append(decision)

    def finalize(
        self,
        *,
        manifest_ref: str | None,
        artifacts: dict[str, str],
    ) -> None:
        self.trajectory.run_manifest_ref = manifest_ref
        self.trajectory.artifacts = dict(sorted(artifacts.items()))

    def write(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(
            self.trajectory.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        path.write_text(redact(encoded) + "\n", encoding="utf-8")
        return path


_ACTIVE_RECORDER: ContextVar[TrajectoryRecorder | None] = ContextVar(
    "deepresearch_trajectory_recorder",
    default=None,
)


@contextmanager
def trajectory_recording(
    recorder: TrajectoryRecorder | None,
) -> Iterator[None]:
    token = _ACTIVE_RECORDER.set(recorder)
    try:
        yield
    finally:
        _ACTIVE_RECORDER.reset(token)


def active_trajectory_recorder() -> TrajectoryRecorder | None:
    return _ACTIVE_RECORDER.get()


def load_trajectory(path: Path) -> AgentTrajectory:
    return AgentTrajectory.model_validate_json(path.read_text(encoding="utf-8"))
