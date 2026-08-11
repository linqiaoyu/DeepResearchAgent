from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from typing import TYPE_CHECKING

from deepresearch_agent.decisions import record_agent_decision
from deepresearch_agent.schemas import AgentDecision, ResearchState

if TYPE_CHECKING:
    from deepresearch_agent.orchestration.decision_context import (
        DecisionContext,
    )


@dataclass
class BranchAllocation:
    branch_id: str
    allocated: int
    used: int = 0
    exhausted: bool = False
    coverage_warning: str | None = None

    @property
    def remaining(self) -> int:
        return max(0, self.allocated - self.used)


@dataclass
class BranchBudget:
    """Deterministic run budget shared by LangGraph Send branches."""

    total_budget: int
    per_branch_cap: int
    #: How many research iterations `total_budget` is meant to cover. R121: the
    #: initial allocation handed out the whole pool, and `reallocate` draws from
    #: what is left, so a first pass sized to spend the pool left nothing for a
    #: second. R120 measured the consequence -- with the loop enabled and
    #: `max_iterations=2`, no refinement pass ran on either question, because
    #: the first pass ended either at the loop's ceiling (20/20) or under the
    #: 20% remaining-budget threshold (17/20). A pool that must cover N
    #: iterations may not be spent by the first one.
    planned_iterations: int = 1
    allocations: dict[str, BranchAllocation] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock, repr=False)

    def __post_init__(self) -> None:
        if self.total_budget < 0:
            raise ValueError("total_budget must be non-negative")
        if self.per_branch_cap < 1:
            raise ValueError("per_branch_cap must be at least 1")
        if self.planned_iterations < 1:
            raise ValueError("planned_iterations must be at least 1")

    @property
    def total_used(self) -> int:
        return sum(item.used for item in self.allocations.values())

    @property
    def total_remaining(self) -> int:
        return max(0, self.total_budget - self.total_used)

    def allocate(
        self,
        branch_ids: list[str],
        state: ResearchState,
        *,
        decision_context: DecisionContext | None = None,
    ) -> dict[str, int]:
        ordered = list(dict.fromkeys(branch_ids))
        if not ordered:
            return {}
        with self._lock:
            self.allocations = {
                branch_id: BranchAllocation(branch_id=branch_id, allocated=0)
                for branch_id in ordered
            }
            # R121: the first iteration takes its share, not the pool. Integer
            # division floors, and at least one call per branch must remain
            # reachable, so the share is never allowed below the branch count.
            iteration_share = max(
                len(ordered),
                self.total_budget // self.planned_iterations,
            )
            distributable = min(
                self.total_budget,
                iteration_share,
                self.per_branch_cap * len(ordered),
            )
            quotient, remainder = divmod(distributable, len(ordered))
            for index, branch_id in enumerate(ordered):
                amount = quotient + (1 if index < remainder else 0)
                self.allocations[branch_id].allocated = min(
                    amount,
                    self.per_branch_cap,
                )
            snapshot = self.snapshot()
        self._record_allocation_decision(
            state,
            decision_type="branch_budget_allocate",
            metrics={branch_id: None for branch_id in ordered},
            outcome="initial_equal_allocation",
            rationale=(
                "divide the run budget equally before LangGraph Send fan-out, "
                "subject to the per-branch cap"
            ),
            decision_context=decision_context,
        )
        return {key: value["allocated"] for key, value in snapshot.items()}

    def reallocate(
        self,
        metrics: dict[str, float],
        state: ResearchState,
        *,
        decision_context: DecisionContext | None = None,
        verify_min_allocation: int = 0,
    ) -> dict[str, int]:
        if verify_min_allocation < 0:
            raise ValueError("verify_min_allocation must be non-negative")
        with self._lock:
            unknown = set(metrics) - set(self.allocations)
            if unknown:
                raise KeyError(f"Unknown branches for reallocation: {sorted(unknown)}")
            available = max(
                0,
                min(
                    self.total_budget,
                    self.per_branch_cap * len(self.allocations),
                )
                - self.total_used,
            )
            for item in self.allocations.values():
                item.allocated = item.used
            verify_branches = (
                {
                    item.sub_question_id
                    for item in decision_context.prior_classifications
                    if item.kind == "verify"
                }
                if decision_context
                else set()
            )
            guaranteed: dict[str, int] = {}
            for branch_id in sorted(verify_branches):
                item = self.allocations.get(branch_id)
                if item is None:
                    continue
                target = min(verify_min_allocation, self.per_branch_cap)
                grant = min(max(0, target - item.allocated), available)
                item.allocated += grant
                available -= grant
                guaranteed[branch_id] = item.allocated
            ordered = sorted(
                self.allocations,
                key=lambda branch_id: (
                    metrics.get(branch_id, float("inf")),
                    branch_id,
                ),
            )
            while available > 0:
                progressed = False
                for branch_id in ordered:
                    item = self.allocations[branch_id]
                    if item.allocated >= self.per_branch_cap:
                        continue
                    item.allocated += 1
                    available -= 1
                    progressed = True
                    if available == 0:
                        break
                if not progressed:
                    break
            warnings = state.metadata.setdefault("coverage_warnings", [])
            for item in self.allocations.values():
                if item.remaining > 0 and item.coverage_warning:
                    if item.coverage_warning in warnings:
                        warnings.remove(item.coverage_warning)
                    item.exhausted = False
                    item.coverage_warning = None
            snapshot = self.snapshot()
        self._record_allocation_decision(
            state,
            decision_type="branch_budget_reallocate",
            metrics=metrics,
            outcome=(
                f"reallocated_with_verify_floor={guaranteed}"
                if guaranteed
                else "reallocated_toward_lower_metric_branches"
            ),
            rationale=(
                "after join, distribute remaining capacity in ascending metric "
                "order while preserving completed work and the per-branch cap"
            ),
            decision_context=decision_context,
            context_fields=(
                (
                    "budget",
                    "sufficiency",
                    "prior_classifications",
                )
                if decision_context
                else ()
            ),
        )
        return {key: value["allocated"] for key, value in snapshot.items()}

    def consume(
        self,
        branch_id: str,
        amount: int,
        state: ResearchState,
    ) -> bool:
        if amount < 0:
            raise ValueError("amount must be non-negative")
        with self._lock:
            if branch_id not in self.allocations:
                raise KeyError(f"Unknown branch: {branch_id}")
            item = self.allocations[branch_id]
            if amount > item.remaining or amount > self.total_remaining:
                self._mark_branch_exhausted(item, state)
                return False
            item.used += amount
            if item.remaining == 0:
                self._mark_branch_exhausted(item, state)
            if self.total_remaining == 0:
                self._mark_total_exhausted(state)
            return True

    def snapshot(self) -> dict[str, dict[str, int | bool | str | None]]:
        return {
            branch_id: {
                "allocated": item.allocated,
                "used": item.used,
                "remaining": item.remaining,
                "exhausted": item.exhausted,
                "coverage_warning": item.coverage_warning,
            }
            for branch_id, item in sorted(self.allocations.items())
        }

    def _mark_branch_exhausted(
        self,
        item: BranchAllocation,
        state: ResearchState,
    ) -> None:
        item.exhausted = True
        item.coverage_warning = (
            f"分支 {item.branch_id} 因分支预算耗尽停止，覆盖可能不足。"
        )
        warnings = state.metadata.setdefault("coverage_warnings", [])
        if item.coverage_warning not in warnings:
            warnings.append(item.coverage_warning)

    def _mark_total_exhausted(self, state: ResearchState) -> None:
        warning = "因总研究预算耗尽，全部分支收敛，覆盖可能不足。"
        warnings = state.metadata.setdefault("coverage_warnings", [])
        if warning not in warnings:
            warnings.append(warning)
        state.metadata.setdefault("branch_budget", {})["total_exhausted"] = True

    def _record_allocation_decision(
        self,
        state: ResearchState,
        *,
        decision_type: str,
        metrics: dict[str, float | None],
        outcome: str,
        rationale: str,
        decision_context: DecisionContext | None = None,
        context_fields: tuple[str, ...] = (),
    ) -> None:
        inputs: dict[str, object] = {
            "metrics": dict(sorted(metrics.items())),
            "allocations": self.snapshot(),
            "total_budget": self.total_budget,
            "total_used": self.total_used,
            "per_branch_cap": self.per_branch_cap,
            "rationale": rationale,
        }
        if decision_context:
            fields = context_fields or ("iteration", "budget")
            inputs["decision_context_fields"] = list(fields)
            inputs["decision_context"] = decision_context.field_snapshot(
                *fields
            )
        record_agent_decision(
            state,
            AgentDecision(
                decision_type=decision_type,
                made_by="BranchBudget",
                inputs=inputs,
                criterion=(
                    "allocate within the run total and per-branch cap; on "
                    "reallocation, lower measured coverage receives capacity first"
                ),
                outcome=outcome,
                alternatives_considered=[
                    "equal_allocation",
                    "reallocate_to_weaker_branches",
                    "stop_exhausted_branches",
                ],
            ),
        )
