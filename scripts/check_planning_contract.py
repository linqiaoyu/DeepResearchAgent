"""Measure the executable planning lifecycle and its negative contracts."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from pydantic import ValidationError

from deepresearch_agent.orchestration import (
    ExecutionPlan,
    PlanBudget,
    PlanLifecycle,
    PlanStep,
)


def _budget(calls: int) -> PlanBudget:
    return PlanBudget(max_calls=calls, max_tokens=100, max_cost_cny=1.0)


def _rejected(factory: Any) -> int:
    try:
        factory()
    except (ValueError, ValidationError):
        return 1
    return 0


def measure() -> dict[str, int | float]:
    plan = ExecutionPlan(
        plan_id="h07-probe",
        budget=PlanBudget(max_calls=4, max_tokens=200, max_cost_cny=2.0),
        steps=[
            PlanStep(
                id="collect",
                objective="collect evidence",
                budget=_budget(2),
                success_condition="evidence recorded",
            ),
            PlanStep(
                id="analyze",
                objective="analyze evidence",
                budget=_budget(2),
                success_condition="analysis recorded",
                depends_on=["collect"],
            ),
        ],
    )
    lifecycle = PlanLifecycle(plan)
    lifecycle.start("collect")
    lifecycle.consume("collect", calls=1, tokens=10, cost_cny=0.1)
    lifecycle.finish("collect", succeeded=True, evidence="source:1")
    lifecycle.start("analyze")
    lifecycle.finish("analyze", succeeded=True, evidence="claim:1")

    invalid_dependency = _rejected(
        lambda: ExecutionPlan(
            plan_id="invalid-dependency",
            budget=_budget(1),
            steps=[
                PlanStep(
                    id="a",
                    objective="a",
                    budget=_budget(1),
                    success_condition="done",
                    depends_on=["missing"],
                )
            ],
        )
    )
    over_budget = _rejected(
        lambda: ExecutionPlan(
            plan_id="over-budget",
            budget=_budget(1),
            steps=[
                PlanStep(
                    id="a",
                    objective="a",
                    budget=_budget(2),
                    success_condition="done",
                )
            ],
        )
    )
    unknown_execution = _rejected(lambda: lifecycle.start("not-planned"))
    statuses = {step.status for step in lifecycle.plan.steps}
    return {
        "steps_with_required_fields": sum(
            bool(
                step.id
                and step.objective
                and step.status
                and step.budget
                and step.success_condition
            )
            for step in lifecycle.plan.steps
        ),
        "plan_steps": len(lifecycle.plan.steps),
        "executed_task_plan_mapping_rate": 1.0
        if not lifecycle.unmapped_executions()
        else 0.0,
        "unused_step_fields": len(lifecycle.unused_step_fields()),
        "invalid_dependency_rejected": invalid_dependency,
        "over_budget_plan_rejected": over_budget,
        "unknown_execution_rejected": unknown_execution,
        "succeeded_steps": sum(step.status == "succeeded" for step in lifecycle.plan.steps),
        "terminal_status_kinds": len(statuses),
    }


def evaluate(metrics: dict[str, Any]) -> list[str]:
    expected = {
        "executed_task_plan_mapping_rate": 1.0,
        "unused_step_fields": 0,
        "invalid_dependency_rejected": 1,
        "over_budget_plan_rejected": 1,
        "unknown_execution_rejected": 1,
    }
    failures = [
        f"{name}: expected {wanted}, got {metrics.get(name)}"
        for name, wanted in expected.items()
        if metrics.get(name) != wanted
    ]
    if metrics.get("steps_with_required_fields") != metrics.get("plan_steps"):
        failures.append("not every plan step has the required lifecycle fields")
    if metrics.get("succeeded_steps") != metrics.get("plan_steps"):
        failures.append("not every executed probe step reached succeeded")
    return failures


def _self_test(metrics: dict[str, Any]) -> None:
    if evaluate(metrics):
        raise SystemExit("planning_contract_self_test=FAIL production probe is dirty")
    cases = {
        "missing_field": {**metrics, "steps_with_required_fields": 1},
        "unmapped_execution": {**metrics, "executed_task_plan_mapping_rate": 0.5},
        "unused_field": {**metrics, "unused_step_fields": 1},
        "dependency_allowed": {**metrics, "invalid_dependency_rejected": 0},
        "over_budget_allowed": {**metrics, "over_budget_plan_rejected": 0},
        "unknown_execution_allowed": {**metrics, "unknown_execution_rejected": 0},
    }
    for label, broken in cases.items():
        if not evaluate(broken):
            raise SystemExit(f"planning_contract_self_test=FAIL accepted {label}")
    print(f"planning_contract_self_test=PASS cases={len(cases) + 1}")


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
