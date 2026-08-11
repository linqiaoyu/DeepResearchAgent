from __future__ import annotations

import unittest

from pydantic import ValidationError

from deepresearch_agent.orchestration import (
    ExecutionPlan,
    PlanBudget,
    PlanLifecycle,
    PlanStep,
)


def _budget(calls: int = 2) -> PlanBudget:
    return PlanBudget(max_calls=calls, max_tokens=100, max_cost_cny=1.0)


class PlanningContractTests(unittest.TestCase):
    def test_dependency_lifecycle_and_execution_mapping(self) -> None:
        lifecycle = PlanLifecycle(
            ExecutionPlan(
                plan_id="p",
                budget=PlanBudget(max_calls=4, max_tokens=200, max_cost_cny=2.0),
                steps=[
                    PlanStep(
                        id="collect",
                        objective="collect evidence",
                        budget=_budget(),
                        success_condition="evidence recorded",
                    ),
                    PlanStep(
                        id="analyze",
                        objective="analyze evidence",
                        budget=_budget(),
                        success_condition="analysis recorded",
                        depends_on=["collect"],
                    ),
                ],
            )
        )
        self.assertEqual(lifecycle.ready_ids(), ["collect"])
        with self.assertRaisesRegex(ValueError, "unmet dependencies"):
            lifecycle.start("analyze")
        task = lifecycle.start("collect")
        self.assertEqual(task.objective, "collect evidence")
        lifecycle.consume("collect", calls=1, tokens=20, cost_cny=0.1)
        lifecycle.finish("collect", succeeded=True, evidence="source:1")
        self.assertEqual(lifecycle.ready_ids(), ["analyze"])
        lifecycle.start("analyze")
        lifecycle.finish("analyze", succeeded=True, evidence="claim:1")
        self.assertEqual(lifecycle.unmapped_executions(), [])
        self.assertEqual(
            [step.status for step in lifecycle.plan.steps],
            ["succeeded", "succeeded"],
        )

    def test_unknown_and_cyclic_dependencies_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValidationError, "unknown dependencies"):
            ExecutionPlan(
                plan_id="p",
                budget=_budget(),
                steps=[
                    PlanStep(
                        id="a",
                        objective="a",
                        budget=_budget(),
                        success_condition="done",
                        depends_on=["missing"],
                    )
                ],
            )
        with self.assertRaisesRegex(ValidationError, "dependency cycle"):
            ExecutionPlan(
                plan_id="p",
                budget=PlanBudget(max_calls=4, max_tokens=200, max_cost_cny=2.0),
                steps=[
                    PlanStep(id="a", objective="a", budget=_budget(), success_condition="done", depends_on=["b"]),
                    PlanStep(id="b", objective="b", budget=_budget(), success_condition="done", depends_on=["a"]),
                ],
            )

    def test_declared_and_runtime_budget_overruns_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValidationError, "exceed plan budget"):
            ExecutionPlan(
                plan_id="p",
                budget=_budget(calls=1),
                steps=[
                    PlanStep(id="a", objective="a", budget=_budget(calls=2), success_condition="done")
                ],
            )
        lifecycle = PlanLifecycle(
            ExecutionPlan(
                plan_id="p",
                budget=_budget(calls=2),
                steps=[
                    PlanStep(id="a", objective="a", budget=_budget(calls=2), success_condition="done")
                ],
            )
        )
        lifecycle.start("a")
        with self.assertRaisesRegex(ValueError, "usage exceeds budget"):
            lifecycle.consume("a", calls=3)

    def test_success_requires_evidence_and_unknown_execution_is_rejected(self) -> None:
        lifecycle = PlanLifecycle(
            ExecutionPlan(
                plan_id="p",
                budget=_budget(),
                steps=[
                    PlanStep(id="a", objective="a", budget=_budget(), success_condition="done")
                ],
            )
        )
        with self.assertRaisesRegex(ValueError, "absent from plan"):
            lifecycle.start("not-planned")
        lifecycle.start("a")
        with self.assertRaisesRegex(ValueError, "without success evidence"):
            lifecycle.finish("a", succeeded=True, evidence="")


if __name__ == "__main__":
    unittest.main()
