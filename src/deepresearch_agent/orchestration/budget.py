from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock

from deepresearch_agent.decisions import record_agent_decision
from deepresearch_agent.schemas import AgentDecision, ResearchState


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
    allocations: dict[str, BranchAllocation] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock, repr=False)

    def __post_init__(self) -> None:
        if self.total_budget < 0:
            raise ValueError("total_budget must be non-negative")
        if self.per_branch_cap < 1:
            raise ValueError("per_branch_cap must be at least 1")

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
    ) -> dict[str, int]:
        ordered = list(dict.fromkeys(branch_ids))
        if not ordered:
            return {}
        with self._lock:
            self.allocations = {
                branch_id: BranchAllocation(branch_id=branch_id, allocated=0)
                for branch_id in ordered
            }
            distributable = min(
                self.total_budget,
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
        )
        return {key: value["allocated"] for key, value in snapshot.items()}

    def reallocate(
        self,
        metrics: dict[str, float],
        state: ResearchState,
    ) -> dict[str, int]:
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
            outcome="reallocated_toward_lower_metric_branches",
            rationale=(
                "after join, distribute remaining capacity in ascending metric "
                "order while preserving completed work and the per-branch cap"
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
    ) -> None:
        record_agent_decision(
            state,
            AgentDecision(
                decision_type=decision_type,
                made_by="BranchBudget",
                inputs={
                    "metrics": dict(sorted(metrics.items())),
                    "allocations": self.snapshot(),
                    "total_budget": self.total_budget,
                    "total_used": self.total_used,
                    "per_branch_cap": self.per_branch_cap,
                    "rationale": rationale,
                },
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
