from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class SpanLabel:
    document_version_id: str
    char_start: int
    char_end: int
    relevance: int


@dataclass(frozen=True)
class ChunkSpan:
    chunk_id: str
    document_version_id: str
    char_start: int
    char_end: int


def resolve_labels_to_chunks(labels: list[SpanLabel], chunks: list[ChunkSpan]) -> dict[str, int]:
    """Map immutable source spans to the current index without storing chunk IDs."""

    relevant: dict[str, int] = {}
    for chunk in chunks:
        for label in labels:
            if (
                label.document_version_id == chunk.document_version_id
                and max(label.char_start, chunk.char_start) < min(label.char_end, chunk.char_end)
            ):
                relevant[chunk.chunk_id] = max(relevant.get(chunk.chunk_id, 0), label.relevance)
    return relevant


def recall_at_k(ranked_ids: list[str], relevant: dict[str, int], k: int) -> float:
    positives = {identifier for identifier, score in relevant.items() if score > 0}
    if not positives:
        return 1.0
    return len(set(ranked_ids[:k]) & positives) / len(positives)


def ndcg_at_k(ranked_ids: list[str], relevant: dict[str, int], k: int) -> float:
    gains = [relevant.get(identifier, 0) for identifier in ranked_ids[:k]]
    actual = sum((2**gain - 1) / math.log2(index + 2) for index, gain in enumerate(gains))
    ideal = sorted(relevant.values(), reverse=True)[:k]
    normalizer = sum((2**gain - 1) / math.log2(index + 2) for index, gain in enumerate(ideal))
    return actual / normalizer if normalizer else 1.0


def validate_retrieval_questions(questions: list[dict[str, object]]) -> None:
    if len(questions) != 60:
        raise ValueError("retrieval_v1 requires exactly 60 questions")
    splits = [question.get("split") for question in questions]
    if splits.count("dev") != 24 or splits.count("test") != 36:
        raise ValueError("retrieval_v1 requires frozen dev=24 test=36 split")
    for question in questions:
        labels = question.get("labels")
        if not isinstance(labels, list) or any("chunk_id" in label for label in labels if isinstance(label, dict)):
            raise ValueError("retrieval labels must be source spans, never chunk_id")
