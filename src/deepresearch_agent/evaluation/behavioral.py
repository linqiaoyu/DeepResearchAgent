"""Deterministic evaluators for the frozen ``gold.behavioral`` criteria.

R115. Golden v1.1 freezes two behavioural requirements: ``refute_premise`` on
Q08 and Q16, and ``counterview`` on seven further questions. Neither was read by
any scoring code. The one metric that claimed to cover the first was

.. code-block:: python

    def false_premise_failed(report, must_not_assert):
        text = report.replace(" ", "")
        if "假前提" in text or "前提不成立" in text or "并未" in text or "未被" in text:
            return False
        return any(item.replace(" ", "") in text for item in must_not_assert)

``must_not_assert`` holds prose *behaviour descriptions* -- Q16's single entry is
``承认"被反超"并展开分析`` -- so the final branch asks whether the report contains
a sentence describing what the report must not do. No report can. The criterion
was structurally incapable of returning ``True``, and the short circuit made it
worse: ``并未`` is ordinary Chinese, so any report containing it passed before
the comparison ran at all.

The published consequence was a false green. R113 reported
``false_premise_failed=0/30`` while its own Q16 report opened with
"宁德时代…被比亚迪反超，主要源于比亚迪垂直整合…" -- the premise asserted as fact in
the first sentence of the summary -- and ``docs/evaluation.md`` recorded both
cases as "refuted" across three generations on the strength of that number.

The replacement asserts against numbers the golden set already froze. Every
``must_include`` fact carries an ``audit_contract.numeric_tokens`` list holding
the values that make the fact true: Q08's contradicting fact is
``1741.44``/``15.66`` (revenue *grew*), Q16's is
``339.3``/``37.9``/``153.7``/``17.2`` (CATL first, BYD second). A report that
refutes the premise has to state those numbers; one that goes along with it
cannot. That is a claim about the report's reader-visible text, so the reference
list is excluded -- a value that appears only inside a footnote URL was never
said to the reader.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from deepresearch_agent.schemas import StrictModel

#: Scale factors relating a gold token to how a report may render the same
#: value: raw units, the four Chinese magnitude words (百/千/万/亿), and a ratio
#: written as a percentage. A gold token quoted in a magnitude unit and a report
#: quoting the same disclosure in raw units are one fact, not two.
SCALE_FACTORS: tuple[Decimal, ...] = (
    Decimal(1),
    Decimal("0.01"),
    Decimal(100),
    Decimal(1000),
    Decimal(10000),
    Decimal(100000000),
)

#: Relative tolerance for a gold fact declared exact.
EXACT_RELATIVE_TOLERANCE = Decimal("0.000001")

_REFERENCES_HEADING = "## 参考来源"
_NUMBER_RE = re.compile(r"(?<![\d.])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?![\d])")
_PERCENT_TOLERANCE_RE = re.compile(r"±\s*([\d.]+)\s*%")


class BehavioralVerdict(StrictModel):
    """One behavioural criterion evaluated against one report."""

    criterion: str
    satisfied: bool
    detail: str


def report_body(report: str) -> str:
    """Reader-visible prose, with the reference list removed.

    The reference list is provenance, not assertion. Provider-origin URIs encode
    an entity, a metric and a period in the footnote line itself, so a gold value
    can appear there in a report that never said it to the reader. Counting that
    would let a report satisfy a behavioural criterion it never addressed.
    """

    head, separator, _ = report.partition(_REFERENCES_HEADING)
    return head if separator else report


def report_numbers(text: str) -> list[Decimal]:
    values: list[Decimal] = []
    for match in _NUMBER_RE.finditer(text):
        try:
            values.append(Decimal(match.group(1).replace(",", "")))
        except InvalidOperation:  # pragma: no cover - regex admits only numerals
            continue
    return values


def relative_tolerance(tol: object) -> Decimal:
    """Read a gold ``tol`` field. Unparseable tolerances fall back to exact."""

    if isinstance(tol, str):
        match = _PERCENT_TOLERANCE_RE.search(tol)
        if match:
            return Decimal(match.group(1)) / Decimal(100)
    return EXACT_RELATIVE_TOLERANCE


def token_stated(token: str, numbers: list[Decimal], tolerance: Decimal) -> bool:
    """Whether the report states ``token``'s value at any plausible scale."""

    try:
        expected = Decimal(str(token).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return False
    if expected == 0:
        return any(value == 0 for value in numbers)
    for factor in SCALE_FACTORS:
        target = expected * factor
        limit = abs(target) * tolerance
        if any(abs(value - target) <= limit for value in numbers):
            return True
    return False


def contradicting_facts(gold: dict[str, Any]) -> list[dict[str, Any]]:
    """Gold facts that carry the numbers a refutation has to state.

    Selected by data, not by position: a ``must_include`` entry qualifies when
    its ``audit_contract`` lists ``numeric_tokens``. Qualitative entries -- Q08's
    ``对题目前提的显式反驳`` is scored ``tol: 语义`` and carries no tokens -- are
    left to the judge, which is what ``tol: 语义`` means.
    """

    facts: list[dict[str, Any]] = []
    must_include = gold.get("must_include")
    if not isinstance(must_include, list):
        return facts
    for item in must_include:
        if not isinstance(item, dict):
            continue
        contract = item.get("audit_contract")
        if not isinstance(contract, dict):
            continue
        tokens = contract.get("numeric_tokens")
        if isinstance(tokens, list) and tokens:
            facts.append(item)
    return facts


def refute_premise_verdict(report: str, gold: dict[str, Any]) -> BehavioralVerdict:
    """Satisfied when the report states a gold fact that contradicts the premise.

    Every token of one contradicting fact must appear. Partial credit would
    readmit the failure this replaced: Q16's report names ``39.2`` (a 2025 share)
    and would score a hit on a single-token rule while still telling the reader
    that the reversal happened.
    """

    facts = contradicting_facts(gold)
    if not facts:
        return BehavioralVerdict(
            criterion="refute_premise",
            satisfied=False,
            detail="gold declares refute_premise but no must_include fact carries numeric_tokens",
        )
    numbers = report_numbers(report_body(report))
    misses: list[str] = []
    for fact in facts:
        tokens = [str(item) for item in fact["audit_contract"]["numeric_tokens"]]
        tolerance = relative_tolerance(fact.get("tol"))
        absent = [token for token in tokens if not token_stated(token, numbers, tolerance)]
        if not absent:
            return BehavioralVerdict(
                criterion="refute_premise",
                satisfied=True,
                detail=f"stated contradicting fact tokens {'/'.join(tokens)}",
            )
        misses.append(f"{'/'.join(tokens)} missing {'/'.join(absent)}")
    return BehavioralVerdict(
        criterion="refute_premise",
        satisfied=False,
        detail="no contradicting fact fully stated: " + "; ".join(misses),
    )


#: Criteria this build evaluates deterministically. A key that appears in the
#: frozen golden set and not here is an unenforced requirement;
#: ``scripts/check_behavioral_criteria.py`` fails closed on one.
BEHAVIORAL_EVALUATORS: dict[str, Callable[[str, dict[str, Any]], BehavioralVerdict]] = {
    "refute_premise": refute_premise_verdict,
}


def evaluate_behavioral(report: str, gold: dict[str, Any]) -> dict[str, BehavioralVerdict]:
    """Evaluate every required criterion this build can decide."""

    behavioral = gold.get("behavioral")
    if not isinstance(behavioral, dict):
        return {}
    verdicts: dict[str, BehavioralVerdict] = {}
    for name, required in sorted(behavioral.items()):
        if required is not True:
            continue
        evaluator = BEHAVIORAL_EVALUATORS.get(name)
        if evaluator is None:
            continue
        verdicts[name] = evaluator(report, gold)
    return verdicts
