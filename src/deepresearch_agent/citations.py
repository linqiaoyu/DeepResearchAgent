from __future__ import annotations

from typing import NamedTuple

from deepresearch_agent.schemas import Evidence


class FootnoteMaps(NamedTuple):
    evidence_id_to_footnote: dict[str, int]
    footnote_to_evidence: dict[int, Evidence]
    unique_refs: list[Evidence]


def build_footnote_maps(evidence_store: list[Evidence]) -> FootnoteMaps:
    evidence_id_to_footnote: dict[str, int] = {}
    footnote_to_evidence: dict[int, Evidence] = {}
    unique_refs: list[Evidence] = []
    key_to_footnote: dict[tuple[str, str], int] = {}

    for item in evidence_store:
        key = (item.source_url, item.claim)
        if key not in key_to_footnote:
            footnote_number = len(unique_refs) + 1
            key_to_footnote[key] = footnote_number
            footnote_to_evidence[footnote_number] = item
            unique_refs.append(item)
        evidence_id_to_footnote[item.id] = key_to_footnote[key]

    return FootnoteMaps(
        evidence_id_to_footnote=evidence_id_to_footnote,
        footnote_to_evidence=footnote_to_evidence,
        unique_refs=unique_refs,
    )
