"""Run the deterministic retrieval_v1 BM25 baseline against authoritative chunks."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from deepresearch_agent.rag.backends import chinese_lexical_terms
from deepresearch_agent.rag.evaluation import ChunkSpan, SpanLabel, ndcg_at_k, recall_at_k, resolve_labels_to_chunks
from deepresearch_agent.storage import SQLiteStore


@dataclass(frozen=True)
class IndexedChunk:
    chunk_id: str
    document_version_id: str
    char_start: int
    char_end: int
    tokens: Counter[str]


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
        if frequency:
            inverse_frequency = math.log(
                1 + (document_count - document_frequency[term] + 0.5) / (document_frequency[term] + 0.5)
            )
            score += inverse_frequency * frequency * 2.2 / (
                frequency + 1.2 * (1 - 0.75 + 0.75 * length / average_length)
            )
    return score


def _rank(query: str, chunks: list[IndexedChunk], *, limit: int) -> list[str]:
    terms = chinese_lexical_terms(query)
    if not terms or not chunks:
        return []
    count = len(chunks)
    average_length = sum(sum(chunk.tokens.values()) for chunk in chunks) / count
    frequencies = {term: sum(term in chunk.tokens for chunk in chunks) for term in set(terms)}
    ranked = [
        (chunk.chunk_id, _bm25(terms, chunk.tokens, frequencies, count, average_length))
        for chunk in chunks
    ]
    return [chunk_id for chunk_id, score in sorted(ranked, key=lambda item: (-item[1], item[0])) if score > 0][:limit]


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def run_baseline(*, database: Path, questions_path: Path, output: Path) -> dict[str, Any]:
    questions = json.loads(questions_path.read_text(encoding="utf-8"))
    if not isinstance(questions, list):
        raise ValueError("questions must be a JSON array")
    store = SQLiteStore(database)
    indexed_by_as_of: dict[str, list[IndexedChunk]] = {}
    spans_by_as_of: dict[str, list[ChunkSpan]] = {}
    rows: list[dict[str, Any]] = []
    for question in questions:
        if not isinstance(question, dict):
            raise ValueError("question must be an object")
        as_of = str(question["as_of"])
        if as_of not in indexed_by_as_of:
            resolved = store.list_ready_chunks(as_of=as_of)
            indexed_by_as_of[as_of] = [
                IndexedChunk(
                    chunk_id=chunk.id,
                    document_version_id=chunk.document_version_id,
                    char_start=chunk.char_start,
                    char_end=chunk.char_end,
                    tokens=Counter(chinese_lexical_terms(chunk.content)),
                )
                for chunk in resolved
            ]
            spans_by_as_of[as_of] = [
                ChunkSpan(chunk.id, chunk.document_version_id, chunk.char_start, chunk.char_end)
                for chunk in resolved
            ]
        labels = [SpanLabel(**label) for label in question["labels"]]
        relevant = resolve_labels_to_chunks(labels, spans_by_as_of[as_of])
        ranked_ids = _rank(str(question["question"]), indexed_by_as_of[as_of], limit=20)
        rows.append(
            {
                "id": question["id"],
                "split": question["split"],
                "question_type": question["question_type"],
                "retrieved": len(ranked_ids),
                "relevant_chunks": len(relevant),
                "recall_at_20": recall_at_k(ranked_ids, relevant, 20),
                "ndcg_at_10": ndcg_at_k(ranked_ids, relevant, 10),
            }
        )
    summary: dict[str, dict[str, float | int]] = {}
    for split in ("dev", "test"):
        subset = [
            row for row in rows if row["split"] == split and row["question_type"] != "refusal"
        ]
        refusals = [
            row for row in rows if row["split"] == split and row["question_type"] == "refusal"
        ]
        summary[split] = {
            "answerable_questions": len(subset),
            "recall_at_20": _mean([float(row["recall_at_20"]) for row in subset]),
            "ndcg_at_10": _mean([float(row["ndcg_at_10"]) for row in subset]),
            "zero_retrieval": sum(row["retrieved"] == 0 for row in subset),
            "zero_relevant": sum(row["relevant_chunks"] == 0 for row in subset),
            "refusal_questions": len(refusals),
            "refusal_nonempty_retrieval": sum(row["retrieved"] > 0 for row in refusals),
        }
    per_type: dict[str, dict[str, float | int]] = {}
    for kind in sorted({str(row["question_type"]) for row in rows}):
        subset = [row for row in rows if row["question_type"] == kind]
        per_type[kind] = {
            "questions": len(subset),
            "recall_at_20": _mean([float(row["recall_at_20"]) for row in subset]),
            "ndcg_at_10": _mean([float(row["ndcg_at_10"]) for row in subset]),
            "zero_retrieval": sum(row["retrieved"] == 0 for row in subset),
        }
    result: dict[str, Any] = {
        "schema_version": 1,
        "backend": "deterministic_chinese_bm25",
        "limit": 20,
        "metrics": summary,
        "metrics_by_question_type": per_type,
        "per_question": rows,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--questions", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = run_baseline(database=args.database, questions_path=args.questions, output=args.output)
    print(json.dumps(result["metrics"], ensure_ascii=False))


if __name__ == "__main__":
    main()
