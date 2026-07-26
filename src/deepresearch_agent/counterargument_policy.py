from __future__ import annotations

import re

from deepresearch_agent.schemas import ResearchState, SubQuestion

_EXPLICIT_COUNTERARGUMENT_RE = re.compile(
    r"risk|counterargument|constraint|compliance|governance|"
    r"风险|反方|限制|合规|治理",
    re.IGNORECASE,
)


def counterargument_required(state: ResearchState) -> bool:
    """Return whether a research plan needs a risk/counterargument lane.

    Exact typed financial lookups are factual retrieval tasks. Requiring a
    counterargument for them creates an unrelated web-search retry. Narrative,
    mixed, untyped, and explicitly risk-oriented plans retain the existing
    counterargument requirement.
    """
    plan = state.plan
    if plan is None or not plan.sub_questions:
        return True
    goal_text = " ".join(
        [
            state.topic,
            plan.topic,
            *plan.success_criteria,
            *(item.question for item in plan.sub_questions),
        ]
    )
    if _EXPLICIT_COUNTERARGUMENT_RE.search(goal_text):
        return True
    return not all(
        _is_exact_financial_lookup(item)
        for item in plan.sub_questions
    )


def _is_exact_financial_lookup(
    sub_question: SubQuestion,
) -> bool:
    return any(
        request.capability == "financial_indicators"
        and bool(request.metrics)
        for request in sub_question.structured_data_requests
    )
