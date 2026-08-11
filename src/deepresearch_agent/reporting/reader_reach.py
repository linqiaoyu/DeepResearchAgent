"""What the reader can actually follow, as opposed to what the run holds.

R116. Citation metrics answer whether the markers a report prints resolve to
Evidence. They do not answer whether a sub-question reached the reader at all,
and the two come apart: across the 30 R113 live reports every citation metric
was green -- ``citation_resolution_rate`` median 1.000, ``uncited_claim_rate``
median 0.000 -- while 8 of 80 sub-questions produced Evidence and arrived as
silence, and 2062 of 2844 Evidence items sat behind footnotes the body never
cited.

Reachability here is deliberately strict in one direction and generous in the
other. A footnote *defined* in the reference list and never cited does not
count: 83% of the reference lines in those reports were never referenced, so
counting definitions would score them as fully covered. A footnote that *is*
cited counts for every Evidence item sharing its reference key, because R107
gives one footnote to a document and R116 extends that rule to a provider
series. ``report_footnote_evidence`` records only the representative; a reader
following its marker reaches every record grouped behind that same footnote.
"""

from __future__ import annotations

import re

from deepresearch_agent.citations import footnote_key
from deepresearch_agent.schemas import ResearchState

_FOOTNOTE_REF_RE = re.compile(r"\[\^(\d+)\]")
_REFERENCES_HEADING = "## 参考来源"


def reader_body(report: str) -> str:
    """The report without its reference list."""

    head, separator, _ = report.partition(_REFERENCES_HEADING)
    return head if separator else report


def evidence_the_reader_can_follow(state: ResearchState, report: str) -> set[str]:
    """Evidence ids reachable from a footnote the body actually cites."""

    footnotes = {
        int(key): value for key, value in (state.report_footnote_evidence or {}).items()
    }
    cited = {int(match) for match in _FOOTNOTE_REF_RE.findall(reader_body(report))}
    representatives = {footnotes[number] for number in cited if number in footnotes}
    reached_reference_keys = {
        footnote_key(item)
        for item in state.evidence_store
        if item.id in representatives
    }
    return {
        item.id
        for item in state.evidence_store
        if item.id in representatives or footnote_key(item) in reached_reference_keys
    }


def orphaned_sub_questions(state: ResearchState, report: str) -> list[tuple[str, int]]:
    """Sub-questions that produced Evidence and reached the reader with none."""

    if state.plan is None:
        return []
    reachable = evidence_the_reader_can_follow(state, report)
    by_sub_question: dict[str, set[str]] = {}
    for item in state.evidence_store:
        by_sub_question.setdefault(item.sub_question_id, set()).add(item.id)
    orphans: list[tuple[str, int]] = []
    for sub_question in state.plan.sub_questions:
        owned = by_sub_question.get(sub_question.id, set())
        if owned and not (owned & reachable):
            orphans.append((sub_question.id, len(owned)))
    return orphans
