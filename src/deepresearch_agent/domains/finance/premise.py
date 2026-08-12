"""Finance relation checks used by the generic Reporter contract."""

from __future__ import annotations

import re

from deepresearch_agent.premise import PremiseAssessment, unresolved_premise
from deepresearch_agent.schemas import Evidence, ReportEvidenceSelection


_OVERTAKE_TOPIC = re.compile(r"被.{1,24}反超")
_DECLINE_TOPIC = re.compile(r"(?:出现|发生).{0,8}(?:下滑|下降)|(?:下滑|下降).{0,8}原因")
_FIRST = re.compile(r"(?:全球|行业|市场)?.{0,18}(?:第一|领先|居首)")
_SECOND = re.compile(r"(?:全球|行业|市场)?.{0,18}(?:第二|次席)")
_DECLINE_DENIAL = re.compile(r"(?:未|没有|并未).{0,10}(?:下滑|下降)|同比增长")
_POSITIVE_OVERTAKE = re.compile(r"(?<!未)(?<!并未)(?<!没有)(?:被|已经|已).{0,12}反超|反超.{0,16}(?:原因|驱动|关键)")
_POSITIVE_DECLINE = re.compile(r"(?:下滑|下降).{0,16}(?:原因|源于|由于)")
_DENIAL = re.compile(r"(?:未|没有|并未).{0,12}(?:反超|下滑|下降)|前提.{0,10}(?:不成立|有误|错误)|实际.{0,12}(?:增长|第一|领先)")


def assess_premise(
    topic: str,
    evidence: list[Evidence],
    selections: list[ReportEvidenceSelection],
) -> PremiseAssessment:
    selected = {
        evidence_id
        for selection in selections
        if selection.status == "selected"
        for evidence_id in selection.evidence_ids
    }
    candidates = [item for item in evidence if item.id in selected]
    if _OVERTAKE_TOPIC.search(topic):
        first = next((item for item in candidates if _FIRST.search(item.claim)), None)
        second = next((item for item in candidates if _SECOND.search(item.claim)), None)
        if first is not None and second is not None:
            return PremiseAssessment(
                status="contradicted",
                premise_kind="overtake",
                evidence_ids=tuple(dict.fromkeys((first.id, second.id))),
                correction_claims=tuple(dict.fromkeys((first.claim, second.claim))),
                reason="selected evidence preserves the opposite first/second ordering",
            )
    if _DECLINE_TOPIC.search(topic):
        denial = next((item for item in candidates if _DECLINE_DENIAL.search(item.claim)), None)
        if denial is not None:
            return PremiseAssessment(
                status="contradicted",
                premise_kind="decline",
                evidence_ids=(denial.id,),
                correction_claims=(denial.claim,),
                reason="selected evidence explicitly denies decline or states growth",
            )
    return unresolved_premise()


def line_adopts_contradicted_premise(line: str, assessment: PremiseAssessment) -> bool:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or _DENIAL.search(stripped):
        return False
    if assessment.premise_kind == "overtake":
        return bool(_POSITIVE_OVERTAKE.search(stripped))
    if assessment.premise_kind == "decline":
        return bool(_POSITIVE_DECLINE.search(stripped))
    return False
