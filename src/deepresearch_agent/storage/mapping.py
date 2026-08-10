"""Row mapping and precondition checks shared by every storage backend.

Both backends used to carry their own copy of this logic, and the copies drifted
in exactly the way duplicated code does: R112 found that SQLite rejected a
malformed ``file_sha256`` while Postgres accepted it, and that Postgres silently
dropped ``filing_date`` from the chunk it returned. Neither divergence was a
decision; both were transcription gaps that no test compared.

Backends differ in their SQL. They must not differ in what a row *means* or in
which inputs they refuse, so those live here once and both backends call in.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping

from deepresearch_agent.schemas import Evidence, TextBoundingBox
from deepresearch_agent.storage.protocol import ResolvedChunk, StoredChunk

_SHA256 = re.compile(r"[0-9a-f]{64}")


def as_json_text(value: object) -> str | None:
    """Normalise a JSON column that one driver returns parsed and another raw."""

    if value is None or isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _json_object(value: object) -> object | None:
    """Parse a stored JSON column, tolerating a column that never held JSON.

    A malformed payload becomes ``None`` rather than an exception: these columns
    are optional enrichment, and a row that predates a schema addition must
    still be readable.
    """

    text = as_json_text(value)
    if not text:
        return None
    try:
        parsed: object = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed


#: Canonical evidence column order. Both backends build their INSERT from this
#: tuple, so a new evidence field cannot reach one backend and miss the other.
EVIDENCE_COLUMNS = (
    "id",
    "research_id",
    "sub_question_id",
    "claim",
    "claim_type",
    "source_kind",
    "source_url",
    "source_title",
    "source_pub_date",
    "extract_text",
    "structured_record_json",
    "numeric_fields_json",
    "numeric_fields_incomplete",
    "source_tier",
    "content_truncated",
    "bbox_json",
    "retrieval_ref_json",
    "confidence",
)


def evidence_fields(item: Evidence) -> dict[str, object]:
    """Serialise evidence to the column values every backend stores."""

    return {
        "id": item.id,
        "research_id": item.research_id,
        "sub_question_id": item.sub_question_id,
        "claim": item.claim,
        "claim_type": item.claim_type,
        "source_kind": item.source_kind,
        "source_url": item.source_url,
        "source_title": item.source_title,
        "source_pub_date": item.source_pub_date.isoformat() if item.source_pub_date else "unknown",
        "extract_text": item.extract_text,
        "structured_record_json": (
            item.structured_record.model_dump_json() if item.structured_record else None
        ),
        "numeric_fields_json": (
            item.numeric_fields.model_dump_json() if item.numeric_fields else None
        ),
        "numeric_fields_incomplete": item.numeric_fields_incomplete,
        "source_tier": item.source_tier,
        "content_truncated": item.content_truncated,
        "bbox_json": item.bbox.model_dump_json() if item.bbox else None,
        "retrieval_ref_json": item.retrieval_ref.model_dump_json() if item.retrieval_ref else None,
        "confidence": item.confidence,
    }


def evidence_from_row(row: Mapping[str, object]) -> Evidence:
    """Rebuild evidence from a stored row, whichever backend produced it.

    Validated rather than constructed. Several ``Evidence`` fields are
    ``Literal`` types, and building the model positionally meant handing an
    arbitrary column string to a field that only accepts three values -- a row
    written by an older schema could produce an ``Evidence`` no code path had
    ever anticipated. Going through ``model_validate`` makes the stored value
    prove it is one of the permitted ones.
    """

    source_pub_date = row["source_pub_date"]
    return Evidence.model_validate(
        {
            "id": str(row["id"]),
            "research_id": str(row["research_id"]),
            "sub_question_id": str(row["sub_question_id"]),
            "claim": str(row["claim"]),
            "claim_type": str(row["claim_type"]),
            "source_kind": str(row["source_kind"]),
            "source_url": str(row["source_url"]),
            "source_title": str(row["source_title"]),
            "source_pub_date": (
                None if source_pub_date in {None, "unknown"} else str(source_pub_date)
            ),
            "extract_text": str(row["extract_text"]),
            "structured_record": _json_object(row["structured_record_json"]),
            "numeric_fields": _json_object(row["numeric_fields_json"]),
            "numeric_fields_incomplete": bool(row["numeric_fields_incomplete"]),
            "source_tier": str(row["source_tier"]),
            "content_truncated": bool(row["content_truncated"]),
            "bbox": _json_object(row["bbox_json"]),
            "retrieval_ref": _json_object(row["retrieval_ref_json"]),
            "confidence": row["confidence"],
        }
    )


def resolved_chunk_from_row(row: Mapping[str, object]) -> ResolvedChunk:
    """Rebuild a resolved chunk, including the disclosure date used for as-of."""

    bbox_items = _json_object(row["bbox_index_json"]) or []
    if not isinstance(bbox_items, list):
        raise ValueError("chunk bbox_index_json must be a list")
    page_number = row["page_number"]
    return ResolvedChunk(
        id=str(row["id"]),
        document_version_id=str(row["document_version_id"]),
        canonical_url=str(row["canonical_url"]),
        char_start=_as_int(row["char_start"]),
        char_end=_as_int(row["char_end"]),
        page_number=None if page_number is None else _as_int(page_number),
        effective_date=str(row["effective_date"]),
        published_at=str(row["published_at"]),
        filing_date=str(row["filing_date"] or ""),
        content=str(row["content"]),
        bbox_index=tuple(TextBoundingBox.model_validate(item) for item in bbox_items),
        entity_id=str(row["entity_id"]),
    )


def _as_int(value: object) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, (str, float)):
        return int(value)
    raise ValueError(f"expected an integer column, got {type(value).__name__}")


#: Columns every backend selects to rebuild a ``ResolvedChunk``. Sharing the
#: list is what stops one backend from quietly returning fewer fields than the
#: other -- the omission of ``document_version.filing_date`` on the Postgres
#: side is precisely how the disclosure date came back empty for 27 rounds.
RESOLVED_CHUNK_COLUMNS = (
    "chunk.id, chunk.document_version_id, document.canonical_url, chunk.char_start, "
    "chunk.char_end, chunk.page_number, chunk.effective_date, chunk.published_at, "
    "document_version.filing_date, chunk.content, chunk.bbox_index_json, chunk.entity_id"
)

RESOLVED_CHUNK_JOIN = (
    "FROM chunk JOIN document_version ON document_version.id = chunk.document_version_id "
    "JOIN document ON document.id = document_version.document_id"
)


def validate_document_version(
    *,
    file_sha256: str,
    effective_date: str,
    chunks: list[StoredChunk],
    published_at: str | None,
) -> str:
    """Refuse an unstorable document version and return its disclosure date.

    Every backend enforces the same preconditions by calling this. When they
    each kept their own copy, Postgres lost the ``file_sha256`` check and would
    have accepted a digest SQLite refused.
    """

    if not chunks:
        raise ValueError("document version must contain at least one located chunk")
    if _SHA256.fullmatch(file_sha256) is None:
        raise ValueError("document file SHA-256 must be a lowercase 64-character digest")
    if any(chunk.char_start < 0 or chunk.char_end <= chunk.char_start for chunk in chunks):
        raise ValueError("chunk character ranges must be non-empty and non-negative")
    if any(chunk.page_number is not None and chunk.page_number < 1 for chunk in chunks):
        raise ValueError("chunk page numbers must be positive when present")
    if any(chunk.effective_date != effective_date for chunk in chunks):
        raise ValueError("every chunk must use the document effective_date")
    resolved = published_at or effective_date
    if any((chunk.published_at or effective_date) != resolved for chunk in chunks):
        raise ValueError("every chunk must use the document published_at")
    return resolved
