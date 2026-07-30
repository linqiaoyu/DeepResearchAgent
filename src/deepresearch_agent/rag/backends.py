"""Concrete RAG backends that resolve all returned text from authoritative storage."""

from __future__ import annotations

import math
import re
from collections import Counter
from datetime import date

from deepresearch_agent.rag.qdrant_index import QdrantIndex
from deepresearch_agent.rag.retrieval import EmbeddingProvider
from deepresearch_agent.rag.search import RetrievalFilter, SearchChunk
from deepresearch_agent.storage import ResolvedChunk, StorageProtocol


def chinese_lexical_terms(text: str) -> tuple[str, ...]:
    """Emit CJK bigrams plus alphanumeric tokens; never fall back to English-only tokenization."""

    terms: list[str] = []
    for run in re.findall(r"[\u3400-\u9fff]+", text):
        terms.extend(run[index : index + 2] for index in range(max(0, len(run) - 1)))
        if len(run) == 1:
            terms.append(run)
    terms.extend(token.lower() for token in re.findall(r"[A-Za-z0-9_]+", text))
    return tuple(terms)


def _as_search_chunk(chunk: ResolvedChunk, *, score: float) -> SearchChunk:
    return SearchChunk(
        chunk_id=chunk.id,
        text=chunk.content,
        effective_date=date.fromisoformat(chunk.effective_date),
        document_version_id=chunk.document_version_id,
        char_start=chunk.char_start,
        char_end=chunk.char_end,
        score=score,
        source_url=chunk.canonical_url,
        bbox_index=chunk.bbox_index,
    )


class StorageLexicalBackend:
    """Deterministic BM25 over ready authoritative chunks, including Chinese terms."""

    fidelity = "real"

    def __init__(self, *, store: StorageProtocol) -> None:
        self.store = store

    def search(self, *, query: str, filters: RetrievalFilter, limit: int) -> list[SearchChunk]:
        if limit < 1 or filters.as_of is None:
            return []
        # This storage schema does not yet store document-type facets.
        # Ignoring a requested facet would make a retrieval claim too broad.
        if filters.doc_types:
            return []
        query_terms = chinese_lexical_terms(query)
        if not query_terms:
            return []
        chunks = self.store.list_ready_chunks(as_of=filters.as_of.isoformat())
        if filters.entity_ids:
            chunks = [chunk for chunk in chunks if chunk.entity_id in filters.entity_ids]
        if filters.period_labels:
            chunks = [
                chunk for chunk in chunks if chunk.effective_date[:4] in filters.period_labels
            ]
        if not chunks:
            return []
        documents = [(chunk, Counter(chinese_lexical_terms(chunk.content))) for chunk in chunks]
        count = len(documents)
        lengths = [sum(tokens.values()) for _, tokens in documents]
        average_length = sum(lengths) / count if count else 0.0
        document_frequency = {
            term: sum(1 for _, tokens in documents if term in tokens) for term in set(query_terms)
        }
        ranked: list[SearchChunk] = []
        for chunk, tokens in documents:
            score = _bm25(query_terms, tokens, document_frequency, count, average_length)
            if score > 0:
                ranked.append(_as_search_chunk(chunk, score=score))
        return sorted(ranked, key=lambda item: (-(item.score or 0.0), item.chunk_id))[:limit]


class QdrantDenseBackend:
    """Dense lookup with Qdrant only as a derived index; hydration is always authoritative."""

    fidelity = "real"

    def __init__(self, *, store: StorageProtocol, index: QdrantIndex, embedding: EmbeddingProvider) -> None:
        self.store = store
        self.index = index
        self.embedding = embedding

    def search(self, *, query: str, filters: RetrievalFilter, limit: int) -> list[SearchChunk]:
        if limit < 1 or filters.as_of is None:
            return []
        if filters.doc_types:
            return []
        vectors = self.embedding.embed([query])
        if len(vectors) != 1:
            raise ValueError("embedding provider must return one query vector")
        hits = self.index.query(
            vector=vectors[0],
            as_of=filters.as_of.isoformat(),
            index_version=filters.index_version,
            limit=limit,
            entity_ids=filters.entity_ids,
            period_labels=filters.period_labels,
        )
        resolved = self.store.resolve_ready_chunks(
            [hit.chunk_id for hit in hits], as_of=filters.as_of.isoformat()
        )
        if filters.entity_ids:
            resolved = [chunk for chunk in resolved if chunk.entity_id in filters.entity_ids]
        scores = {hit.chunk_id: hit.score for hit in hits}
        return [_as_search_chunk(chunk, score=scores[chunk.id]) for chunk in resolved]


def _bm25(
    query_terms: tuple[str, ...],
    document_terms: Counter[str],
    document_frequency: dict[str, int],
    document_count: int,
    average_length: float,
) -> float:
    length = sum(document_terms.values())
    if not length or not average_length:
        return 0.0
    score = 0.0
    for term in query_terms:
        frequency = document_terms[term]
        if not frequency:
            continue
        idf = math.log(1 + (document_count - document_frequency[term] + 0.5) / (document_frequency[term] + 0.5))
        score += idf * frequency * 2.2 / (frequency + 1.2 * (1 - 0.75 + 0.75 * length / average_length))
    return score
