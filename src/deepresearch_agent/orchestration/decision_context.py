from __future__ import annotations

from collections.abc import Mapping

from pydantic import ConfigDict

from deepresearch_agent.schemas import ResearchState, StrictModel


class FrozenDecisionModel(StrictModel):
    """Immutable value object used inside a run-scoped decision view."""

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        frozen=True,
    )


class BranchBalance(FrozenDecisionModel):
    branch_id: str
    allocated: int
    used: int
    remaining: int


class BudgetContext(FrozenDecisionModel):
    total: int
    used: int
    remaining: int
    branches: tuple[BranchBalance, ...] = ()


class SufficiencyContext(FrozenDecisionModel):
    sub_question_id: str
    score: float
    sufficient: bool
    gaps: tuple[str, ...] = ()


class PriorClassificationContext(FrozenDecisionModel):
    sub_question_id: str
    kind: str


class CriticIssueContext(FrozenDecisionModel):
    issue_type: str
    severity: str
    message: str
    sub_question_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()


class ReflectionSignalContext(FrozenDecisionModel):
    persistently_weak_subquestions: tuple[str, ...] = ()
    repeatedly_ineffective_sources: tuple[str, ...] = ()
    repeated_critic_issue_types: tuple[tuple[str, int], ...] = ()
    ineffective_replanning_iterations: tuple[int, ...] = ()

    @property
    def present(self) -> bool:
        return any(
            (
                self.persistently_weak_subquestions,
                self.repeatedly_ineffective_sources,
                self.repeated_critic_issue_types,
                self.ineffective_replanning_iterations,
            )
        )


class DecisionContext(FrozenDecisionModel):
    """Read-only aggregate through which decisions observe one another."""

    iteration: int = 0
    budget: BudgetContext = BudgetContext(total=0, used=0, remaining=0)
    sufficiency: tuple[SufficiencyContext, ...] = ()
    prior_classifications: tuple[PriorClassificationContext, ...] = ()
    unresolved_critic_issues: tuple[CriticIssueContext, ...] = ()
    reflection_signals: ReflectionSignalContext = ReflectionSignalContext()

    def field_snapshot(self, *fields: str) -> dict[str, object]:
        payload = self.model_dump(mode="json")
        return {field: payload[field] for field in fields}


def build_decision_context(
    state: ResearchState,
    *,
    iteration: int = 0,
    budget_total: int | None = None,
    budget_used: int | None = None,
    budget_snapshot: Mapping[
        str,
        Mapping[str, int | bool | str | None],
    ]
    | None = None,
    sufficiency: object | None = None,
) -> DecisionContext:
    """Build an immutable view without adding mutable state to ResearchState."""

    raw_budget = state.metadata.get("branch_budget", {})
    if not isinstance(raw_budget, Mapping):
        raw_budget = {}
    raw_allocations = (
        budget_snapshot
        if budget_snapshot is not None
        else raw_budget.get("allocations", {})
    )
    if not isinstance(raw_allocations, Mapping):
        raw_allocations = {}
    branches = tuple(
        BranchBalance(
            branch_id=str(branch_id),
            allocated=int(item.get("allocated", 0)),
            used=int(item.get("used", 0)),
            remaining=int(item.get("remaining", 0)),
        )
        for branch_id, item in sorted(raw_allocations.items())
        if isinstance(item, Mapping)
    )
    total = int(
        budget_total
        if budget_total is not None
        else raw_budget.get("total_budget", 0)
    )
    used = int(
        budget_used
        if budget_used is not None
        else raw_budget.get("total_used", sum(item.used for item in branches))
    )

    sufficiency_rows = _sufficiency_rows(
        sufficiency
        if sufficiency is not None
        else state.metadata.get("research_sufficiency")
    )
    prior_rows = _prior_rows(state)
    issue_rows = _issue_rows(state)
    reflection_signals = _reflection_signals(state)
    return DecisionContext(
        iteration=iteration,
        budget=BudgetContext(
            total=total,
            used=used,
            remaining=max(0, total - used),
            branches=branches,
        ),
        sufficiency=sufficiency_rows,
        prior_classifications=prior_rows,
        unresolved_critic_issues=issue_rows,
        reflection_signals=reflection_signals,
    )


def _sufficiency_rows(raw: object) -> tuple[SufficiencyContext, ...]:
    if hasattr(raw, "model_dump"):
        raw = raw.model_dump(mode="json")
    if not isinstance(raw, Mapping):
        return ()
    rows = raw.get("by_sub_question", [])
    if not isinstance(rows, list):
        return ()
    return tuple(
        SufficiencyContext(
            sub_question_id=str(item.get("sub_question_id", "")),
            score=round(1.0 - len(item.get("gaps", [])) / 6, 6),
            sufficient=bool(item.get("sufficient", False)),
            gaps=tuple(str(gap) for gap in item.get("gaps", [])),
        )
        for item in rows
        if isinstance(item, Mapping)
    )


def _prior_rows(
    state: ResearchState,
) -> tuple[PriorClassificationContext, ...]:
    raw = state.metadata.get("prior_memory", {})
    if not isinstance(raw, Mapping):
        return ()
    rows = raw.get("classifications", [])
    if not isinstance(rows, list):
        return ()
    return tuple(
        PriorClassificationContext(
            sub_question_id=str(item.get("sub_question_id", "")),
            kind=str(item.get("kind", "")),
        )
        for item in rows
        if isinstance(item, Mapping)
    )


def _issue_rows(state: ResearchState) -> tuple[CriticIssueContext, ...]:
    if not state.critic_report or not state.plan:
        return ()
    evidence_to_subquestion = {
        item.id: item.sub_question_id for item in state.evidence_store
    }
    all_subquestions = tuple(
        item.id for item in state.plan.sub_questions
    )
    rows: list[CriticIssueContext] = []
    for issue in state.critic_report.issues:
        targets: set[str] = set()
        if (
            issue.suggested_retry_task
            and issue.suggested_retry_task.sub_question_id
        ):
            targets.add(issue.suggested_retry_task.sub_question_id)
        evidence_ids = tuple(
            item
            for item in issue.affected_claims
            if item in evidence_to_subquestion
        )
        targets.update(
            evidence_to_subquestion[item] for item in evidence_ids
        )
        if not targets:
            targets.update(all_subquestions)
        rows.append(
            CriticIssueContext(
                issue_type=issue.issue_type,
                severity=issue.severity,
                message=issue.message,
                sub_question_ids=tuple(sorted(targets)),
                evidence_ids=evidence_ids,
            )
        )
    return tuple(rows)


def _reflection_signals(state: ResearchState) -> ReflectionSignalContext:
    result = state.metadata.get("reflection_result", {})
    raw = (
        result.get("deterministic_signals", {})
        if isinstance(result, Mapping)
        else {}
    )
    if not isinstance(raw, Mapping):
        return ReflectionSignalContext()
    repeated = raw.get("repeated_critic_issue_types", {})
    return ReflectionSignalContext(
        persistently_weak_subquestions=tuple(
            sorted(
                str(item)
                for item in raw.get(
                    "persistently_weak_subquestions",
                    [],
                )
            )
        ),
        repeatedly_ineffective_sources=tuple(
            sorted(
                str(item)
                for item in raw.get(
                    "repeatedly_ineffective_sources",
                    [],
                )
            )
        ),
        repeated_critic_issue_types=tuple(
            (str(key), int(value))
            for key, value in sorted(
                repeated.items()
                if isinstance(repeated, Mapping)
                else []
            )
        ),
        ineffective_replanning_iterations=tuple(
            sorted(
                int(item)
                for item in raw.get(
                    "ineffective_replanning_iterations",
                    [],
                )
            )
        ),
    )
