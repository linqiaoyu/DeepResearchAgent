from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
import hashlib
import json
from typing import Any, Literal, Protocol, runtime_checkable
from urllib.parse import urlsplit

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

    status: Literal[
        "pending_llm_reasoning",
        "recorded_placeholder",
        "cache_miss",
    ] = "pending_llm_reasoning"
    insights: list["StrategyInsight"] = Field(default_factory=list)
    quality_validation: Literal[
        "unverifiable_in_deterministic_mode"
    ] = "unverifiable_in_deterministic_mode"
    provider: str | None = None
    cache_key: str | None = None
    cache_miss_reason: str | None = None
    must_stop: bool = False


class StrategyInsight(StrictModel):
    target_type: Literal["subquestion", "source", "replanning", "global"]
    target: str
    recommendation: str
    rationale: str


class ReflectionTrajectorySummary(StrictModel):
    run_id: str
    tool_call_count: int = Field(ge=0)
    node_transition_count: int = Field(ge=0)
    decision_types: tuple[str, ...] = ()
    node_names: tuple[str, ...] = ()


class ReflectionReasoningRequest(StrictModel):
    deterministic_signals: DeterministicReflectionSignals
    trajectory_summary: ReflectionTrajectorySummary


@runtime_checkable
class ReflectionReasoningInterface(Protocol):
    """019 seam: schema-stable strategy reasoning over extracted facts."""

    def reason(
        self,
        request: ReflectionReasoningRequest,
    ) -> ReflectionLLMInsight:
        ...


class SyntheticFixtureReflectionReasoner:
    """Zero-API adapter proving the reasoning seam is wired, not useful."""

    def reason(
        self,
        request: ReflectionReasoningRequest,
    ) -> ReflectionLLMInsight:
        key = reflection_request_key(request)
        return ReflectionLLMInsight(
            status="recorded_placeholder",
            insights=[
                StrategyInsight(
                    target_type="global",
                    target="fixture_pipeline",
                    recommendation=(
                        "retain deterministic behavior; do not auto-adopt "
                        "this synthetic placeholder"
                    ),
                    rationale=(
                        "the fixture adapter validates schema and routing "
                        "only; judgment quality requires 019"
                    ),
                )
            ],
            provider="synthetic_fixture",
            cache_key=key,
        )


class RecordedReflectionReasoner:
    """Exact-match replay adapter that fails closed on unseen inputs."""

    def __init__(
        self,
        responses: Mapping[str, ReflectionLLMInsight],
    ) -> None:
        self._responses = {
            str(key): value.model_copy(deep=True)
            for key, value in responses.items()
        }

    def reason(
        self,
        request: ReflectionReasoningRequest,
    ) -> ReflectionLLMInsight:
        key = reflection_request_key(request)
        response = self._responses.get(key)
        if response is None:
            return ReflectionLLMInsight(
                status="cache_miss",
                provider="recorded_replay",
                cache_key=key,
                cache_miss_reason=(
                    "unseen reflection signal combination; stop and report "
                    "rather than fabricate strategy insight"
                ),
                must_stop=True,
            )
        return response.model_copy(
            deep=True,
            update={"cache_key": key},
        )


class ReflectionResult(StrictModel):
    """Additive artifact separating observable facts from model judgment."""

    deterministic_signals: DeterministicReflectionSignals = Field(
        default_factory=DeterministicReflectionSignals
    )
    llm_insight: ReflectionLLMInsight = Field(
        default_factory=ReflectionLLMInsight
    )


class Reflector:
    """Read-only dual-track reflector.

    Research sufficiency is an immediate, single-round stop criterion.
    Deterministic reflection signals instead aggregate observable patterns
    across rounds. They supply facts for later strategy reasoning but do not
    themselves judge which strategy should be adopted.
    """

    def __init__(
        self,
        reasoner: ReflectionReasoningInterface | None = None,
    ) -> None:
        self.reasoner = reasoner or SyntheticFixtureReflectionReasoner()

    def reflect(
        self,
        trajectory: AgentTrajectory,
        decisions: list[AgentDecision],
        *,
        reasoning_request: ReflectionReasoningRequest | None = None,
    ) -> ReflectionResult:
        copied_trajectory = trajectory.model_copy(deep=True)
        copied_decisions = [
            item.model_copy(deep=True) for item in decisions
        ]
        signals = self._extract_signals(
            copied_trajectory,
            copied_decisions,
        )
        request = reasoning_request or self.reasoning_request(
            copied_trajectory,
            copied_decisions,
            signals=signals,
        )
        return ReflectionResult(
            deterministic_signals=signals,
            llm_insight=self.reasoner.reason(request),
        )

    def reasoning_request(
        self,
        trajectory: AgentTrajectory,
        decisions: list[AgentDecision],
        *,
        signals: DeterministicReflectionSignals | None = None,
    ) -> ReflectionReasoningRequest:
        extracted = signals or self._extract_signals(
            trajectory,
            decisions,
        )
        return ReflectionReasoningRequest(
            deterministic_signals=extracted,
            trajectory_summary=ReflectionTrajectorySummary(
                run_id=trajectory.run_id,
                tool_call_count=len(trajectory.tool_calls),
                node_transition_count=len(trajectory.node_transitions),
                decision_types=tuple(
                    sorted({item.decision_type for item in decisions})
                ),
                node_names=tuple(
                    item.node for item in trajectory.node_transitions
                ),
            ),
        )

    def signal_extraction_decision(
        self,
        trajectory: AgentTrajectory,
        decisions: list[AgentDecision],
        signals: DeterministicReflectionSignals,
    ) -> AgentDecision:
        source_fragments = {
            "trajectory_run_id": trajectory.run_id,
            "tool_call_count": len(trajectory.tool_calls),
            "node_transition_count": len(trajectory.node_transitions),
            "decision_types": sorted(
                {item.decision_type for item in decisions}
            ),
            "signal_sources": [
                "AgentTrajectory.tool_calls",
                "AgentTrajectory.node_transitions",
                "ResearchState.agent_decisions",
            ],
        }
        counts = {
            "persistently_weak_subquestions": len(
                signals.persistently_weak_subquestions
            ),
            "repeatedly_ineffective_sources": len(
                signals.repeatedly_ineffective_sources
            ),
            "repeated_critic_issue_types": len(
                signals.repeated_critic_issue_types
            ),
            "ineffective_replanning_iterations": len(
                signals.ineffective_replanning_iterations
            ),
        }
        return AgentDecision(
            decision_type="reflection_signal_extraction",
            made_by="Reflector",
            inputs={**source_fragments, "signal_counts": counts},
            criterion=(
                "mechanically aggregate repeated cross-round observations; "
                "do not infer strategy quality or adopt a strategy"
            ),
            outcome=f"extracted_signal_counts={counts}",
            alternatives_considered=[
                "omit_empty_signal_categories",
                "infer_strategy_recommendations",
                "record_all_four_mechanical_categories",
            ],
        )

    def _extract_signals(
        self,
        trajectory: AgentTrajectory,
        decisions: list[AgentDecision],
    ) -> DeterministicReflectionSignals:
        return DeterministicReflectionSignals(
            persistently_weak_subquestions=(
                _persistently_weak_subquestions(decisions)
            ),
            repeatedly_ineffective_sources=(
                _repeatedly_ineffective_sources(trajectory)
            ),
            repeated_critic_issue_types=(
                _repeated_critic_issue_types(trajectory)
            ),
            ineffective_replanning_iterations=(
                _ineffective_replanning_iterations(decisions)
            ),
        )


def _persistently_weak_subquestions(
    decisions: Iterable[AgentDecision],
) -> list[str]:
    round_gaps: list[set[str]] = []
    for decision in decisions:
        if decision.decision_type != "research_replan":
            continue
        raw = decision.inputs.get("gaps_by_sub_question")
        if not isinstance(raw, Mapping):
            continue
        round_gaps.append(
            {
                str(subquestion_id)
                for subquestion_id, gaps in raw.items()
                if isinstance(gaps, list) and bool(gaps)
            }
        )
    if len(round_gaps) < 2:
        return []
    return sorted(set.intersection(*round_gaps))


def _repeatedly_ineffective_sources(
    trajectory: AgentTrajectory,
) -> list[str]:
    retrieved: Counter[str] = Counter()
    for call in trajectory.tool_calls:
        if call.tool_spec.get("name") != "web_search" or call.error:
            continue
        domains_in_call: set[str] = set()
        for item in call.result if isinstance(call.result, list) else []:
            if not isinstance(item, Mapping):
                continue
            domain = _domain(item.get("url"))
            if domain:
                domains_in_call.add(domain)
        retrieved.update(domains_in_call)
    accepted = {
        str(domain)
        for transition in trajectory.node_transitions
        for domain in _string_list(
            transition.output_summary.get("evidence_source_domains")
        )
    }
    return sorted(
        domain
        for domain, count in retrieved.items()
        if count >= 2 and domain not in accepted
    )


def _repeated_critic_issue_types(
    trajectory: AgentTrajectory,
) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for transition in trajectory.node_transitions:
        if transition.node != "critic":
            continue
        counts.update(
            _string_list(
                transition.output_summary.get("critic_issue_types")
            )
        )
    return {
        issue_type: count
        for issue_type, count in sorted(counts.items())
        if count >= 2
    }


def _ineffective_replanning_iterations(
    decisions: Iterable[AgentDecision],
) -> list[int]:
    replanned = {
        item.iteration
        for item in decisions
        if item.decision_type == "research_replan"
        and item.iteration is not None
    }
    ineffective: set[int] = set()
    for decision in decisions:
        if (
            decision.decision_type != "bounded_loop_control"
            or decision.iteration not in replanned
            or decision.iteration is None
        ):
            continue
        before = _number(decision.inputs.get("metric_before"))
        after = _number(decision.inputs.get("metric_after"))
        if before is not None and after is not None and after <= before:
            ineffective.add(decision.iteration)
    return sorted(ineffective)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item) for item in value]


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _domain(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    parsed = urlsplit(value)
    return parsed.netloc.lower() or parsed.scheme.lower()


def reflection_request_key(request: ReflectionReasoningRequest) -> str:
    payload = request.model_dump(mode="json")
    trajectory_summary = payload.get("trajectory_summary", {})
    if isinstance(trajectory_summary, dict):
        # A run id identifies an execution, not the reflection intent. Keeping
        # it in the key made byte-identical reasoning inputs miss across runs.
        trajectory_summary.pop("run_id", None)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
