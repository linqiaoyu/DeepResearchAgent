from __future__ import annotations

import argparse
import inspect
import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from deepresearch_agent.reflection import (
    ReflectionLLMInsight,
    ReflectionProposal,
    ReflectionProposalEvidence,
    Reflector,
)
from deepresearch_agent.trajectory import AgentTrajectory


ROOT = Path(__file__).resolve().parents[1]
QUALITY_NODE = ROOT / "src/deepresearch_agent/workflow/nodes/quality.py"


def collect_metrics() -> dict[str, int | float]:
    trajectory = AgentTrajectory(
        run_id="reflection-contract",
        request={"topic": "reflection contract"},
    )
    result = Reflector().reflect(trajectory, [])
    proposals = result.llm_insight.insights
    complete = sum(
        bool(item.target.strip())
        and bool(item.expected_effect.strip())
        and bool(item.supporting_evidence)
        for item in proposals
    )

    invalid_rejections = 0
    invalid_cases: tuple[dict[str, Any], ...] = (
        {
            "target": "",
            "recommendation": "retry official sources",
            "expected_effect": "improve provenance",
            "supporting_evidence": [_evidence()],
        },
        {
            "target": "pipeline",
            "recommendation": "   ",
            "expected_effect": "improve provenance",
            "supporting_evidence": [_evidence()],
        },
        {
            "target": "pipeline",
            "recommendation": "retry official sources",
            "expected_effect": "improve provenance",
            "supporting_evidence": [],
        },
    )
    for values in invalid_cases:
        try:
            ReflectionProposal(
                target_type="global",
                rationale="contract counterexample",
                **values,
            )
        except ValidationError:
            invalid_rejections += 1

    synthetic_quality_rejections = 0
    try:
        ReflectionLLMInsight(
            status="recorded_placeholder",
            provider="synthetic_fixture",
            reasoner_kind="synthetic_fixture",
            quality_bearing=True,
        )
    except ValidationError:
        synthetic_quality_rejections = 1

    reflect_parameters = inspect.signature(Reflector.reflect).parameters
    state_parameters = sum(
        name in {"state", "research_state"}
        for name in reflect_parameters
    )
    quality_source = QUALITY_NODE.read_text(encoding="utf-8")
    typed_artifacts = int(
        result.deterministic_signals.__class__.__name__
        == "DeterministicReflectionSignals"
    ) + int(
        all(item.__class__.__name__ == "ReflectionProposal" for item in proposals)
        and bool(proposals)
    )
    return {
        "typed_reflection_artifacts": typed_artifacts,
        "proposal_contract_coverage": (
            complete / len(proposals) if proposals else 0.0
        ),
        "invalid_proposals_rejected": invalid_rejections,
        "synthetic_quality_claim_rejections": synthetic_quality_rejections,
        "reflector_state_parameters": state_parameters,
        "proposal_artifact_storage_sites": quality_source.count(
            'state.metadata["reflection_result"] = result.model_dump'
        ),
    }


def _evidence() -> ReflectionProposalEvidence:
    return ReflectionProposalEvidence(
        artifact_type="trajectory_summary",
        reference="trajectory_summary.tool_call_count",
        observation="the bounded fixture trajectory was inspected",
    )


def validate(metrics: dict[str, int | float]) -> list[str]:
    expected: dict[str, int | float] = {
        "typed_reflection_artifacts": 2,
        "proposal_contract_coverage": 1.0,
        "invalid_proposals_rejected": 3,
        "synthetic_quality_claim_rejections": 1,
        "reflector_state_parameters": 0,
        "proposal_artifact_storage_sites": 1,
    }
    return [
        f"{key}: expected {target!r}, got {metrics.get(key)!r}"
        for key, target in expected.items()
        if metrics.get(key) != target
    ]


def self_test() -> None:
    metrics = collect_metrics()
    failures = validate(metrics)
    if failures:
        raise SystemExit("\n".join(failures))
    counterexample = dict(metrics)
    counterexample["proposal_contract_coverage"] = 0.0
    if not validate(counterexample):
        raise SystemExit("negative self-test did not reject incomplete proposals")
    print(json.dumps(metrics, ensure_ascii=False, sort_keys=True))
    print("positive_fixture=PASS negative_fixture=PASS")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    metrics = collect_metrics()
    failures = validate(metrics)
    print(json.dumps(metrics, ensure_ascii=False, sort_keys=True))
    if failures:
        raise SystemExit("\n".join(failures))
    if args.self_test:
        counterexample = dict(metrics)
        counterexample["typed_reflection_artifacts"] = 1
        if not validate(counterexample):
            raise SystemExit("negative self-test accepted merged artifacts")
        print("positive_fixture=PASS negative_fixture=PASS")


if __name__ == "__main__":
    main()
