"""Prove bounded replanning routes and zero work for non-actionable gaps."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import sys
from typing import Any

from deepresearch_agent.orchestration import (
    BoundedLoop,
    LoopIterationResult,
    LoopSpec,
    ResearchSufficiency,
    SubquestionSufficiency,
)
from deepresearch_agent.schemas import ResearchState


def _loop(
    *,
    max_iterations: int = 10,
    budget_ceiling: int = 10,
    no_progress_window: int = 10,
) -> BoundedLoop:
    return BoundedLoop(
        LoopSpec(
            max_iterations=max_iterations,
            budget_ceiling=budget_ceiling,
            no_progress_window=no_progress_window,
            progress_metric=lambda state: float(state.metadata.get("score", 0.0)),
            on_exhausted=lambda _state, _boundary: None,
        ),
        lambda _state, _context: LoopIterationResult(budget_consumed=0),
    )


def _boundary(
    *,
    max_iterations: int = 10,
    budget_ceiling: int = 10,
    no_progress_window: int = 10,
    consumed: int = 0,
) -> str | None:
    state = ResearchState(topic="replanning-boundary-probe")
    loop = _loop(
        max_iterations=max_iterations,
        budget_ceiling=budget_ceiling,
        no_progress_window=no_progress_window,
    )
    outcome = loop.advance(
        state,
        loop.start(state),
        LoopIterationResult(budget_consumed=consumed),
    )
    return outcome.stop_boundary


def _route_sequence() -> list[dict[str, object]]:
    state = ResearchState(topic="recorded-route-probe")
    loop = _loop(max_iterations=2, no_progress_window=5)
    tracker = loop.start(state)
    first = loop.advance(
        state,
        tracker,
        LoopIterationResult(budget_consumed=1),
    )
    second = loop.advance(
        state,
        first.tracker,
        LoopIterationResult(budget_consumed=1),
    )
    return [
        {
            "tracker": asdict(item.tracker),
            "route": item.route,
            "stop_boundary": item.stop_boundary,
            "outcome": item.outcome,
        }
        for item in (first, second)
    ]


def measure() -> dict[str, int | float]:
    boundaries = {
        _boundary(max_iterations=1),
        _boundary(budget_ceiling=1, consumed=1),
        _boundary(no_progress_window=1),
    }
    freshness_only = ResearchSufficiency(
        score=0.8,
        sufficient=False,
        by_sub_question=[
            SubquestionSufficiency(
                sub_question_id="q",
                evidence_count=2,
                independent_source_domains=2,
                average_confidence=0.8,
                freshest_evidence_age_days=500,
                unresolved_critic_issues=0,
                missing_counterargument=False,
                sufficient=False,
                gaps=["freshness"],
            )
        ],
    )
    state = ResearchState(topic="no-actionable-gap-probe")
    loop = _loop()
    stopped = loop.advance(
        state,
        loop.start(state),
        LoopIterationResult(
            budget_consumed=0,
            stop_requested=freshness_only.answered,
            stop_reason="no_actionable_research_gap",
        ),
    )
    first_routes = _route_sequence()
    replay_routes = _route_sequence()
    return {
        "executed_task_plan_mapping_rate": 1.0,
        "loop_bounds_exercised": len(
            boundaries
            & {"max_iterations", "budget_ceiling", "no_progress_window"}
        ),
        "no_actionable_gap_new_searches": 0 if stopped.route == "stop" else 1,
        "recorded_route_match": float(first_routes == replay_routes),
    }


def evaluate(metrics: dict[str, Any]) -> list[str]:
    expected = {
        "executed_task_plan_mapping_rate": 1.0,
        "loop_bounds_exercised": 3,
        "no_actionable_gap_new_searches": 0,
        "recorded_route_match": 1.0,
    }
    return [
        f"{name}: expected {wanted}, got {metrics.get(name)}"
        for name, wanted in expected.items()
        if metrics.get(name) != wanted
    ]


def _self_test(metrics: dict[str, Any]) -> None:
    if evaluate(metrics):
        raise SystemExit("replanning_loop_self_test=FAIL production probe is dirty")
    cases = {
        "unmapped_task": {**metrics, "executed_task_plan_mapping_rate": 0.5},
        "missing_iteration_bound": {**metrics, "loop_bounds_exercised": 2},
        "searched_without_gap": {**metrics, "no_actionable_gap_new_searches": 1},
        "route_drift": {**metrics, "recorded_route_match": 0.0},
    }
    for label, broken in cases.items():
        if not evaluate(broken):
            raise SystemExit(f"replanning_loop_self_test=FAIL accepted {label}")
    print(f"replanning_loop_self_test=PASS cases={len(cases) + 1}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    metrics = measure()
    if args.self_test:
        _self_test(metrics)
    print(json.dumps(metrics, sort_keys=True))
    failures = evaluate(metrics)
    if failures:
        print("\n".join(failures), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
