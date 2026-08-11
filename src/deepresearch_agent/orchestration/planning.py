"""Domain-neutral, bounded lifecycle for executable plans."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from pydantic import Field, model_validator

from deepresearch_agent.schemas import StrictModel


PlanStepStatus = Literal["pending", "running", "succeeded", "failed", "skipped"]


class PlanBudget(StrictModel):
    max_calls: int = Field(ge=0)
    max_tokens: int = Field(ge=0)
    max_cost_cny: float = Field(ge=0)


class PlanUsage(StrictModel):
    calls: int = Field(default=0, ge=0)
    tokens: int = Field(default=0, ge=0)
    cost_cny: float = Field(default=0.0, ge=0)


class PlanStep(StrictModel):
    id: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    status: PlanStepStatus = "pending"
    budget: PlanBudget
    success_condition: str = Field(min_length=1)
    depends_on: list[str] = Field(default_factory=list)
    usage: PlanUsage = Field(default_factory=PlanUsage)
    success_evidence: str | None = None


class ExecutionPlan(StrictModel):
    plan_id: str = Field(min_length=1)
    steps: list[PlanStep] = Field(min_length=1)
    budget: PlanBudget

    @model_validator(mode="after")
    def validate_graph_and_budget(self) -> ExecutionPlan:
        ids = [step.id for step in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("plan step ids must be unique")
        known = set(ids)
        for step in self.steps:
            unknown = set(step.depends_on) - known
            if unknown:
                raise ValueError(
                    f"plan step {step.id} has unknown dependencies={sorted(unknown)}"
                )
            if step.id in step.depends_on:
                raise ValueError(f"plan step {step.id} cannot depend on itself")
        self._reject_cycles()
        totals = PlanBudget(
            max_calls=sum(step.budget.max_calls for step in self.steps),
            max_tokens=sum(step.budget.max_tokens for step in self.steps),
            max_cost_cny=sum(step.budget.max_cost_cny for step in self.steps),
        )
        exceeded = [
            name
            for name in ("max_calls", "max_tokens", "max_cost_cny")
            if getattr(totals, name) > getattr(self.budget, name)
        ]
        if exceeded:
            raise ValueError(f"plan step budgets exceed plan budget: {exceeded}")
        return self

    def _reject_cycles(self) -> None:
        dependencies = {step.id: set(step.depends_on) for step in self.steps}
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(step_id: str) -> None:
            if step_id in visiting:
                raise ValueError(f"plan dependency cycle includes {step_id}")
            if step_id in visited:
                return
            visiting.add(step_id)
            for dependency in dependencies[step_id]:
                visit(dependency)
            visiting.remove(step_id)
            visited.add(step_id)

        for step_id in dependencies:
            visit(step_id)


class PlanLifecycle:
    """The sole mutator for step status, usage, and completion evidence."""

    CONSUMED_STEP_FIELDS = frozenset(
        {
            "id",
            "objective",
            "status",
            "budget",
            "success_condition",
            "depends_on",
            "usage",
            "success_evidence",
        }
    )

    def __init__(self, plan: ExecutionPlan) -> None:
        self.plan = plan.model_copy(deep=True)
        self._steps = {step.id: step for step in self.plan.steps}
        self.executed_task_ids: list[str] = [
            step.id for step in self.plan.steps if step.status != "pending"
        ]

    @classmethod
    def from_snapshot(cls, value: dict[str, object]) -> PlanLifecycle:
        return cls(ExecutionPlan.model_validate(value))

    def ready_ids(self) -> list[str]:
        succeeded = {
            step.id for step in self.plan.steps if step.status == "succeeded"
        }
        return [
            step.id
            for step in self.plan.steps
            if step.status == "pending" and set(step.depends_on) <= succeeded
        ]

    def start(self, task_id: str) -> PlanStep:
        step = self._known_step(task_id)
        if step.status != "pending":
            raise ValueError(f"plan step {task_id} is not pending")
        unmet = [
            dependency
            for dependency in step.depends_on
            if self._steps[dependency].status != "succeeded"
        ]
        if unmet:
            raise ValueError(f"plan step {task_id} has unmet dependencies={unmet}")
        step.status = "running"
        self.executed_task_ids.append(task_id)
        # Returning the whole typed step makes objective and budget explicit inputs
        # to an executor rather than display-only plan metadata.
        return step.model_copy(deep=True)

    def consume(
        self,
        task_id: str,
        *,
        calls: int = 0,
        tokens: int = 0,
        cost_cny: float = 0.0,
    ) -> None:
        step = self._known_step(task_id)
        if step.status != "running":
            raise ValueError(f"plan step {task_id} is not running")
        proposed = PlanUsage(
            calls=step.usage.calls + calls,
            tokens=step.usage.tokens + tokens,
            cost_cny=step.usage.cost_cny + cost_cny,
        )
        self._reject_usage_over_budget(proposed, step.budget, scope=task_id)
        aggregate = self._aggregate_usage(extra=(task_id, proposed))
        self._reject_usage_over_budget(aggregate, self.plan.budget, scope="plan")
        step.usage = proposed

    def finish(self, task_id: str, *, succeeded: bool, evidence: str) -> None:
        step = self._known_step(task_id)
        if step.status != "running":
            raise ValueError(f"plan step {task_id} is not running")
        rendered = evidence.strip()
        if succeeded and not rendered:
            raise ValueError(
                f"plan step {task_id} satisfied '{step.success_condition}' "
                "without success evidence"
            )
        step.status = "succeeded" if succeeded else "failed"
        step.success_evidence = rendered or None

    def snapshot(self) -> dict[str, object]:
        return self.plan.model_dump(mode="json")

    def unmapped_executions(self) -> list[str]:
        known = set(self._steps)
        return [task_id for task_id in self.executed_task_ids if task_id not in known]

    def unused_step_fields(self) -> list[str]:
        return sorted(set(PlanStep.model_fields) - self.CONSUMED_STEP_FIELDS)

    def _known_step(self, task_id: str) -> PlanStep:
        try:
            return self._steps[task_id]
        except KeyError as exc:
            raise ValueError(f"executed task {task_id} is absent from plan") from exc

    def _aggregate_usage(
        self,
        *,
        extra: tuple[str, PlanUsage] | None = None,
    ) -> PlanUsage:
        usages: Iterable[PlanUsage] = (
            extra[1] if extra and step.id == extra[0] else step.usage
            for step in self.plan.steps
        )
        rows = list(usages)
        return PlanUsage(
            calls=sum(item.calls for item in rows),
            tokens=sum(item.tokens for item in rows),
            cost_cny=sum(item.cost_cny for item in rows),
        )

    @staticmethod
    def _reject_usage_over_budget(
        usage: PlanUsage,
        budget: PlanBudget,
        *,
        scope: str,
    ) -> None:
        exceeded = [
            name
            for name, used_name in (
                ("max_calls", "calls"),
                ("max_tokens", "tokens"),
                ("max_cost_cny", "cost_cny"),
            )
            if getattr(usage, used_name) > getattr(budget, name)
        ]
        if exceeded:
            raise ValueError(f"{scope} usage exceeds budget: {exceeded}")


def make_parallel_execution_plan(
    *,
    plan_id: str,
    tasks: list[tuple[str, str]],
    max_calls_per_step: int,
    max_tokens: int,
    max_cost_cny: float,
) -> ExecutionPlan:
    """Adapt independent domain-planned tasks into the Harness contract."""
    count = len(tasks)
    if count == 0:
        raise ValueError("execution plan requires at least one task")
    token_base, token_remainder = divmod(max_tokens, count)
    cost_share = max_cost_cny / count
    steps = [
        PlanStep(
            id=task_id,
            objective=objective,
            budget=PlanBudget(
                max_calls=max_calls_per_step,
                max_tokens=token_base + (1 if index < token_remainder else 0),
                max_cost_cny=cost_share,
            ),
            success_condition="research attempt is recorded",
        )
        for index, (task_id, objective) in enumerate(tasks)
    ]
    return ExecutionPlan(
        plan_id=plan_id,
        steps=steps,
        budget=PlanBudget(
            max_calls=max_calls_per_step * count,
            max_tokens=max_tokens,
            max_cost_cny=max_cost_cny,
        ),
    )
