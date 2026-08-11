from __future__ import annotations

import argparse
import json
from pathlib import Path

from deepresearch_agent.reflection import (
    RecordedReflectionReasoner,
    ReflectionExecutionLimits,
    ReflectionExecutionUsage,
    ReflectionLLMInsight,
    ReflectionLimitExceeded,
    ReflectionProposal,
    ReflectionProposalEvidence,
    ReflectionReasoningEstimate,
    ReflectionReasoningRequest,
    Reflector,
    reflection_request_key,
)
from deepresearch_agent.settings import Settings
from deepresearch_agent.trajectory import AgentTrajectory


ROOT = Path(__file__).resolve().parents[1]
REFLECTION_SOURCE = ROOT / "src/deepresearch_agent/reflection.py"


class FixtureReasoner:
    def __init__(self, estimate: ReflectionReasoningEstimate) -> None:
        self._estimate = estimate
        self.calls = 0

    def estimate(
        self,
        request: ReflectionReasoningRequest,
    ) -> ReflectionReasoningEstimate:
        del request
        return self._estimate

    def reason(
        self,
        request: ReflectionReasoningRequest,
    ) -> ReflectionLLMInsight:
        del request
        self.calls += 1
        return _proposal_insight(
            prompt_tokens=self._estimate.prompt_tokens,
            completion_tokens=self._estimate.max_completion_tokens,
            cost_cny=self._estimate.estimated_cost_cny,
        )


def _proposal() -> ReflectionProposal:
    return ReflectionProposal(
        target_type="source",
        target="secondary.example",
        recommendation="replace repeated source with a primary filing",
        rationale="the source repeatedly produced no accepted evidence",
        expected_effect="increase accepted primary evidence",
        supporting_evidence=[
            ReflectionProposalEvidence(
                artifact_type="deterministic_signal",
                reference="repeatedly_ineffective_sources[0]",
                observation="secondary.example repeated without evidence",
            )
        ],
    )


def _proposal_insight(
    *,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    cost_cny: float = 0.0,
) -> ReflectionLLMInsight:
    return ReflectionLLMInsight(
        status="recorded_placeholder",
        insights=[_proposal()],
        provider="fixture_live_boundary",
        reasoner_kind="live",
        quality_bearing=True,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_cny=cost_cny,
    )


def collect_metrics() -> dict[str, int | float]:
    trajectory = AgentTrajectory(run_id="adoption", request={"topic": "x"})
    estimate = ReflectionReasoningEstimate(
        prompt_tokens=10,
        max_completion_tokens=10,
        estimated_cost_cny=0.01,
    )
    adopted = Reflector(FixtureReasoner(estimate)).reflect(trajectory, [])
    rejected = Reflector().reflect(trajectory, [])
    decisions = [*adopted.adoption_decisions, *rejected.adoption_decisions]
    unauthorized = sum(
        item.verdict == "adopted" and item.decided_by != "DecisionGate"
        for item in decisions
    )
    reason_coverage = sum(bool(item.reason.strip()) for item in decisions) / len(
        decisions
    )

    hard_bounds = 0
    calls_after_refusal = 0
    cases = (
        (
            ReflectionExecutionLimits(max_invocations=1),
            ReflectionExecutionUsage(invocations=1),
        ),
        (
            ReflectionExecutionLimits(max_prompt_tokens=5),
            ReflectionExecutionUsage(),
        ),
        (
            ReflectionExecutionLimits(max_completion_tokens=5),
            ReflectionExecutionUsage(),
        ),
        (
            ReflectionExecutionLimits(max_cost_cny=0.005),
            ReflectionExecutionUsage(),
        ),
    )
    for limits, usage in cases:
        reasoner = FixtureReasoner(estimate)
        try:
            Reflector(reasoner, limits=limits).reflect(
                trajectory,
                [],
                prior_usage=usage,
            )
        except ReflectionLimitExceeded:
            hard_bounds += 1
        calls_after_refusal += reasoner.calls

    first_request = Reflector().reasoning_request(
        AgentTrajectory(run_id="recorded-a", request={"topic": "same"}),
        [],
    )
    recorded = ReflectionLLMInsight(
        status="recorded_placeholder",
        insights=[_proposal()],
        provider="recorded_fixture",
    )
    replay = Reflector(
        RecordedReflectionReasoner(
            {reflection_request_key(first_request): recorded}
        )
    )
    first = replay.reflect(
        AgentTrajectory(run_id="recorded-a", request={"topic": "same"}),
        [],
    )
    second = replay.reflect(
        AgentTrajectory(run_id="recorded-b", request={"topic": "same"}),
        [],
    )
    reflection_source = REFLECTION_SOURCE.read_text(encoding="utf-8")
    return {
        "unauthorized_reflection_adoptions": unauthorized,
        "adopted_decisions": sum(
            item.verdict == "adopted" for item in decisions
        ),
        "rejected_decisions": sum(
            item.verdict == "rejected" for item in decisions
        ),
        "adoption_reason_coverage": reason_coverage,
        "hard_reflection_bounds_exercised": hard_bounds,
        "reasoner_calls_after_bound_refusal": calls_after_refusal,
        "recorded_reasoner_replay_match": float(
            first.model_dump_json() == second.model_dump_json()
        ),
        "decision_gate_call_sites": reflection_source.count(
            "DecisionGate.authorize_reflection_proposal("
        ),
        "default_reflection_enabled": int(
            Settings(storage_path=Path("contract.db")).reflection_enabled
        ),
    }


def validate(metrics: dict[str, int | float]) -> list[str]:
    expected: dict[str, int | float] = {
        "unauthorized_reflection_adoptions": 0,
        "adopted_decisions": 1,
        "rejected_decisions": 1,
        "adoption_reason_coverage": 1.0,
        "hard_reflection_bounds_exercised": 4,
        "reasoner_calls_after_bound_refusal": 0,
        "recorded_reasoner_replay_match": 1.0,
        "decision_gate_call_sites": 1,
        "default_reflection_enabled": 0,
    }
    return [
        f"{key}: expected {target!r}, got {metrics.get(key)!r}"
        for key, target in expected.items()
        if metrics.get(key) != target
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    metrics = collect_metrics()
    failures = validate(metrics)
    print(json.dumps(metrics, sort_keys=True))
    if failures:
        raise SystemExit("\n".join(failures))
    if args.self_test:
        broken = dict(metrics)
        broken["unauthorized_reflection_adoptions"] = 1
        if not validate(broken):
            raise SystemExit("negative self-test accepted unauthorized adoption")
        print("reflection_adoption_self_test=PASS positive=1 negative=1")


if __name__ == "__main__":
    main()
