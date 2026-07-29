from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from pypdf import PdfReader

from deepresearch_agent.rag.chunking import Chunk, LocatedText, chunk_located_text
from deepresearch_agent.storage import StorageProtocol, StoredChunk


@dataclass(frozen=True)
class CorpusEntry:
    path: str
    url: str
    sha256: str
    bytes: int
    retrieved_at: str
    public_accessibility: str
    effective_date: str


@dataclass(frozen=True)
class IngestReport:
    chunks: int
    dropped_unresolvable: int
    superseded_chunks: int


def load_corpus(path: Path) -> dict[str, CorpusEntry]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    entries = payload.get("documents", payload) if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        raise ValueError("corpus manifest must be a list or contain documents")
    result: dict[str, CorpusEntry] = {}
    required = {"path", "url", "sha256", "bytes", "retrieved_at", "public_accessibility", "effective_date"}
    for value in entries:
        if not isinstance(value, dict) or required - value.keys():
            raise ValueError(f"invalid corpus entry; required={sorted(required)}")
        entry = CorpusEntry(**{name: value[name] for name in required})
        date.fromisoformat(entry.effective_date)
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
            chunks=[
                StoredChunk(
                    id=chunk.id,
                    char_start=chunk.char_start,
                    char_end=chunk.char_end,
                    page_number=chunk.page,
                    effective_date=chunk.effective_date,
                    content=chunk.text,
                )
                for chunk in chunks
            ],
        )
        total_chunks += result.active_chunks
        superseded_chunks += result.superseded_chunks
    return IngestReport(total_chunks, 0, superseded_chunks)


def _extract(path: Path, *, max_pdf_pages: int | None = None) -> list[LocatedText]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        sections: list[LocatedText] = []
        offset = 0
        for page_number, page in enumerate(PdfReader(path).pages, 1):
            if max_pdf_pages is not None and page_number > max_pdf_pages:
                break
            text = page.extract_text() or ""
            sections.append(LocatedText(text=text, page=page_number, char_start=offset))
            offset += len(text) + 1
        return sections
    text = path.read_text(encoding="utf-8")
    if suffix in {".html", ".htm"}:
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text)
    return [LocatedText(text=text, page=None, char_start=0)]
