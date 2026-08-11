from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pdfplumber

from deepresearch_agent.rag.chunking import Chunk, LocatedText, LocatedTextBox, chunk_located_text
from deepresearch_agent.schemas import BoundingBox, TextBoundingBox
from deepresearch_agent.storage import StorageProtocol, StoredChunk


#: A disclosure date the manifest did not actually establish. Entries carrying
#: one of these are dated by substitution, not by a registry, and retrieval that
#: trusts them is exposed to lookahead bias. R112 measured the exposure on the
#: shipped corpus at a median of 109 days.
SUBSTITUTED_DISCLOSURE_SOURCES = frozenset({"", "retrieved_at_fallback", "effective_date_fallback"})


@dataclass(frozen=True)
class CorpusEntry:
    path: str
    url: str
    sha256: str
    bytes: int
    retrieved_at: str
    public_accessibility: str
    effective_date: str
    published_at: str = ""
    published_at_source: str = ""

    @property
    def disclosure_is_substituted(self) -> bool:
        """True when nothing established this document's publication date."""

        return not self.published_at or self.published_at_source in SUBSTITUTED_DISCLOSURE_SOURCES


@dataclass(frozen=True)
class IngestReport:
    chunks: int
    dropped_unresolvable: int
    superseded_chunks: int
    added_chunks: int
    removed_chunks: int
    #: Documents whose disclosure date was substituted rather than established.
    #: An index built from these cannot answer an as-of question honestly, so
    #: the number is reported rather than left for a reader to infer.
    substituted_disclosure_documents: int = 0


def load_corpus(path: Path) -> dict[str, CorpusEntry]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    entries = payload.get("documents", payload) if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        raise ValueError("corpus manifest must be a list or contain documents")
    result: dict[str, CorpusEntry] = {}
    required = {
        "path",
        "url",
        "sha256",
        "bytes",
        "retrieved_at",
        "public_accessibility",
        "effective_date",
    }
    for value in entries:
        if not isinstance(value, dict) or required - value.keys():
            raise ValueError(f"invalid corpus entry; required={sorted(required)}")
        entry = CorpusEntry(
            **{name: value[name] for name in required},
            published_at=str(value.get("published_at", "")),
            published_at_source=str(value.get("published_at_source", "")),
        )
        date.fromisoformat(entry.effective_date)
        if entry.published_at:
            date.fromisoformat(entry.published_at)
        if entry.published_at and entry.published_at < entry.effective_date:
            raise ValueError(f"published_at precedes effective_date: {entry.path}")
        if entry.path in result:
            raise ValueError(f"duplicate corpus path: {entry.path}")
        result[entry.path] = entry
    return result


def ingest_corpus(
    *, input_dir: Path, corpus_path: Path, max_pdf_pages: int | None = None
) -> list[Chunk]:
    """Verify a local corpus manifest and return deterministic, located chunks."""

    manifest = load_corpus(corpus_path)
    chunks: list[Chunk] = []
    for relative_path, entry in sorted(manifest.items()):
        path = (input_dir / relative_path).resolve()
        if input_dir.resolve() not in path.parents or not path.is_file():
            raise ValueError(f"manifest document missing from input directory: {relative_path}")
        raw = path.read_bytes()
        actual_hash = hashlib.sha256(raw).hexdigest()
        if actual_hash != entry.sha256 or len(raw) != entry.bytes:
            raise ValueError(f"manifest integrity mismatch: {relative_path}")
        chunks.extend(
            chunk_located_text(
                document_sha256=actual_hash,
                sections=_extract(path, max_pdf_pages=max_pdf_pages),
                effective_date=entry.effective_date,
            )
        )
    return chunks


def ingest_and_persist(
    *, input_dir: Path, corpus_path: Path, store: StorageProtocol, max_pdf_pages: int | None = None
) -> IngestReport:
    """Ingest only manifest-listed local files and atomically persist versions."""

    manifest = load_corpus(corpus_path)
    before_chunk_ids = {chunk.id for chunk in store.list_ready_chunks(as_of="9999-12-31")}
    total_chunks = 0
    superseded_chunks = 0
    for relative_path, entry in sorted(manifest.items()):
        path = (input_dir / relative_path).resolve()
        if input_dir.resolve() not in path.parents or not path.is_file():
            raise ValueError(f"manifest document missing from input directory: {relative_path}")
        raw = path.read_bytes()
        actual_hash = hashlib.sha256(raw).hexdigest()
        if actual_hash != entry.sha256 or len(raw) != entry.bytes:
            raise ValueError(f"manifest integrity mismatch: {relative_path}")
        chunks = chunk_located_text(
            document_sha256=actual_hash,
            sections=_extract(path, max_pdf_pages=max_pdf_pages),
            effective_date=entry.effective_date,
        )
        result = store.record_document_version(
            canonical_url=entry.url,
            file_sha256=actual_hash,
            effective_date=entry.effective_date,
            # Not `or entry.effective_date`. A manifest that does not state a
            # disclosure date has not established one, and substituting the
            # period end here is the same lookahead bias one layer up.
            published_at=entry.published_at,
            published_at_source=entry.published_at_source,
            chunks=[
                StoredChunk(
                    id=chunk.id,
                    char_start=chunk.char_start,
                    char_end=chunk.char_end,
                    page_number=chunk.page,
                    effective_date=chunk.effective_date,
                    content=chunk.text,
                    published_at=entry.published_at,
                    published_at_source=entry.published_at_source,
                    bbox_index=chunk.bbox_index,
                    entity_id=_source_entity_id(relative_path),
                )
                for chunk in chunks
            ],
        )
        total_chunks += result.active_chunks
        superseded_chunks += result.superseded_chunks
    after_chunk_ids = {chunk.id for chunk in store.list_ready_chunks(as_of="9999-12-31")}
    return IngestReport(
        chunks=total_chunks,
        dropped_unresolvable=0,
        superseded_chunks=superseded_chunks,
        added_chunks=len(after_chunk_ids - before_chunk_ids),
        removed_chunks=len(before_chunk_ids - after_chunk_ids),
        substituted_disclosure_documents=sum(
            1 for entry in manifest.values() if entry.disclosure_is_substituted
        ),
    )


def _extract(path: Path, *, max_pdf_pages: int | None = None) -> list[LocatedText]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        sections: list[LocatedText] = []
        offset = 0
        with pdfplumber.open(path) as pdf:
            for page_number, page in enumerate(pdf.pages, 1):
                if max_pdf_pages is not None and page_number > max_pdf_pages:
                    break
                words = page.extract_words() or []
                parts: list[str] = []
                bbox_spans: list[LocatedTextBox] = []
                position = 0
                for word in words:
                    value = str(word.get("text") or "").strip()
                    if not value:
                        continue
                    if parts:
                        position += 1
                    start = position
                    position += len(value)
                    parts.append(value)
                    bbox_spans.append(
                        LocatedTextBox(
                            char_start=start,
                            char_end=position,
                            value=TextBoundingBox(
                                text=value,
                                bbox=BoundingBox(
                                    page=page_number,
                                    x0=float(word["x0"]),
                                    top=float(word["top"]),
                                    x1=float(word["x1"]),
                                    bottom=float(word["bottom"]),
                                ),
                            ),
                        )
                    )
                text = " ".join(parts)
                sections.append(
                    LocatedText(
                        text=text,
                        page=page_number,
                        char_start=offset,
                        bbox_spans=tuple(bbox_spans),
                    )
                )
                offset += len(text) + 1
        return sections
    text = path.read_text(encoding="utf-8")
    if suffix in {".html", ".htm"}:
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text)
    return [LocatedText(text=text, page=None, char_start=0)]


def _source_entity_id(relative_path: str) -> str:
    """Use the manifest filename's stable source identifier, not document text."""

    stem = Path(relative_path).stem
    entity_id = stem.split("_", 1)[0].lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", entity_id):
        raise ValueError(f"corpus path lacks a stable entity identifier: {relative_path}")
    return entity_id
