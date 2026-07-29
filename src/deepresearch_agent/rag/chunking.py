from __future__ import annotations

import hashlib
from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5


# The version is deliberately decomposable: strategy, target, overlap,
# tokenizer identifier, and tokenizer version.  This is recorded with every
# chunk so a changed approximation cannot silently reuse an old index.
CHUNKER_VERSION = "heading_page_first:512:128:chars:4"
TARGET_CHARS = 512 * 4
OVERLAP_CHARS = 128 * 4


@dataclass(frozen=True)
class LocatedText:
    text: str
    page: int | None
    char_start: int


@dataclass(frozen=True)
class Chunk:
    id: str
    document_sha256: str
    text: str
    page: int | None
    char_start: int
    char_end: int
    effective_date: str
    chunker_version: str = CHUNKER_VERSION


def chunk_located_text(*, document_sha256: str, sections: list[LocatedText], effective_date: str) -> list[Chunk]:
    """Create stable overlapping chunks while retaining a source-page pointer."""

    chunks: list[Chunk] = []
    for section in sections:
        text = section.text.strip()
        if not text:
            continue
        start = 0
        while start < len(text):
            end = min(len(text), start + TARGET_CHARS)
            value = text[start:end]
            absolute_start = section.char_start + start
            absolute_end = absolute_start + len(value)
            content_hash = hashlib.sha256(value.encode("utf-8")).hexdigest()
            chunks.append(
                Chunk(
                    id=str(uuid5(NAMESPACE_URL, f"{document_sha256}:{absolute_start}:{absolute_end}:{content_hash}")),
                    document_sha256=document_sha256,
                    text=value,
                    page=section.page,
                    char_start=absolute_start,
                    char_end=absolute_end,
                    effective_date=effective_date,
                )
            )
            if end == len(text):
                break
            start = end - OVERLAP_CHARS
    return chunks
