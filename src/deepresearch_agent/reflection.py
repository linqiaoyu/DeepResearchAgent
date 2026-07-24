from __future__ import annotations

from typing import Literal

from pydantic import Field

from deepresearch_agent.schemas import AgentDecision, StrictModel
from deepresearch_agent.trajectory import AgentTrajectory


class DeterministicReflectionSignals(StrictModel):
    """Mechanically extracted cross-iteration facts, populated in stage 2."""

    persistently_weak_subquestions: list[str] = Field(default_factory=list)
    repeatedly_ineffective_sources: list[str] = Field(default_factory=list)
    repeated_critic_issue_types: dict[str, int] = Field(default_factory=dict)
    ineffective_replanning_iterations: list[int] = Field(
        default_factory=list
    )


class ReflectionLLMInsight(StrictModel):
    """Explicit reasoning seam whose judgment quality is deferred to 019."""

    status: Literal["pending_llm_reasoning"] = "pending_llm_reasoning"
    insights: list[str] = Field(default_factory=list)
    quality_validation: Literal[
        "unverifiable_in_deterministic_mode"
    ] = "unverifiable_in_deterministic_mode"


class ReflectionResult(StrictModel):
    """Additive artifact separating observable facts from model judgment."""

    deterministic_signals: DeterministicReflectionSignals = Field(
        default_factory=DeterministicReflectionSignals
    )
    llm_insight: ReflectionLLMInsight = Field(
        default_factory=ReflectionLLMInsight
    )


class Reflector:
    """Read-only dual-track reflection skeleton.

    Stage 1 intentionally leaves deterministic aggregation and the LLM
    reasoning adapter unimplemented. The empty signals and pending marker are
    explicit protocol states, not claims that reflection judgment occurred.
    """

    def reflect(
        self,
        trajectory: AgentTrajectory,
        decisions: list[AgentDecision],
    ) -> ReflectionResult:
        # Touch both forward-protocol inputs without deriving signals yet.
        # Deep copies make the read-only boundary explicit to callers.
        trajectory.model_copy(deep=True)
        [item.model_copy(deep=True) for item in decisions]
        return ReflectionResult()
