from __future__ import annotations

from typing import NamedTuple
from urllib.parse import urlsplit

from deepresearch_agent.schemas import Evidence

#: URL schemes that identify a document. Everything else is a provider-origin
#: URI, which identifies a single record inside a series.
_DOCUMENT_SCHEMES = frozenset({"http", "https", ""})


class FootnoteMaps(NamedTuple):
    evidence_id_to_footnote: dict[str, int]
    footnote_to_evidence: dict[int, Evidence]
    unique_refs: list[Evidence]
    #: How many Evidence items each footnote covers. A reference standing for a
    #: series must say so; its representative URI names one record of it.
    footnote_record_counts: dict[int, int]


def footnote_key(item: Evidence) -> str:
    """What makes two Evidence items one reference.

    R107 grouped by source URL, which is right for a document: two sentences
    read out of the same filing are one source and get one footnote. It is
    wrong for a provider series, where every record carries its own URI --
    ``akshare://<metric>/<symbol>/<date>/<hash>`` -- so a year of daily prices
    became a year of references.

    R116's reader measurement found what that costs. Across the 30 R113 live
    reports the reference lists ran to 1269 lines, 1056 of them (83%) never
    cited from the body; 969 were provider-series records. One report was 766
    lines, 736 of them references, of which the body cited three: 242 trading
    days times three price fields, one line each.

    A provider series is therefore keyed by what it is a series *of* -- the
    scheme and the title the provider gave it -- and a document is still keyed
    by its URL. Grouping only merges records that already share a title, so two
    metrics from one provider stay apart.
    """

    scheme = urlsplit(item.source_url).scheme
    if scheme in _DOCUMENT_SCHEMES:
        return item.source_url
    return f"{scheme}://{item.source_title}"


def build_footnote_maps(evidence_store: list[Evidence]) -> FootnoteMaps:
    evidence_id_to_footnote: dict[str, int] = {}
    footnote_to_evidence: dict[int, Evidence] = {}
    unique_refs: list[Evidence] = []
    key_to_footnote: dict[str, int] = {}
    footnote_record_counts: dict[int, int] = {}

    for item in evidence_store:
        key = footnote_key(item)
        if key not in key_to_footnote:
            footnote_number = len(unique_refs) + 1
            key_to_footnote[key] = footnote_number
            footnote_to_evidence[footnote_number] = item
            unique_refs.append(item)
        number = key_to_footnote[key]
        evidence_id_to_footnote[item.id] = number
        footnote_record_counts[number] = footnote_record_counts.get(number, 0) + 1

    return FootnoteMaps(
        evidence_id_to_footnote=evidence_id_to_footnote,
        footnote_to_evidence=footnote_to_evidence,
        unique_refs=unique_refs,
        footnote_record_counts=footnote_record_counts,
    )
