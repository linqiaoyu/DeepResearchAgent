"""Evaluate the frozen retrieval_v1 split with RRF Top-50 and rerank Top-8."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

from deepresearch_agent.llm import LLMClient
from deepresearch_agent.rag.backends import QdrantDenseBackend, StorageLexicalBackend
from deepresearch_agent.rag.evaluation import ChunkSpan, SpanLabel, ndcg_at_k, recall_at_k, resolve_labels_to_chunks
from deepresearch_agent.rag.qdrant_index import QdrantIndex
from deepresearch_agent.rag.retrieval import (
    DashScopeEmbeddingProvider,
    DashScopeRerankerProvider,
    ProviderPricing,
    rrf_fuse,
)
from deepresearch_agent.rag.search import RetrievalFilter
from deepresearch_agent.storage import SQLiteStore

TOP_K = 50
RERANK_TOP_N = 8
PRICE_SOURCE = "aliyun_model_studio_public_20260729"


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def evaluate(
    *,
    database: Path,
    questions: Path,
    split: str,
    index_version: str,
    output: Path,
    budget_cny: float,
    env: dict[str, str | None],
) -> dict[str, Any]:
    if split not in {"dev", "test"}:
        raise ValueError("split must be dev or test")
    required = ("DASHSCOPE_API_KEY", "DEEPRESEARCH_QDRANT_URL", "DEEPRESEARCH_QDRANT_COLLECTION")
    if any(not (env.get(name) or "").strip() for name in required):
        raise ValueError("DashScope and Qdrant configuration are required")
    store = SQLiteStore(database)
    run_id = f"047-hybrid-{split}-{index_version}"
    ledger = LLMClient(
        ledger_path=output.with_name(f"hybrid_{split}_ledger.jsonl"),
        global_ledger_path=Path("data/runtime/llm_ledger.jsonl"),
        budget_cny=budget_cny,
        completion_func=lambda **_: {},
    )
    ledger.start_run(run_id)
    embedding = DashScopeEmbeddingProvider(
        api_key=str(env["DASHSCOPE_API_KEY"]),
        ledger=ledger,
        run_id=run_id,
        pricing=ProviderPricing(0.5, PRICE_SOURCE),
        dimensions=1024,
        max_batch_size=10,
    )
    reranker = DashScopeRerankerProvider(
        api_key=str(env["DASHSCOPE_API_KEY"]),
        ledger=ledger,
        run_id=run_id,
        pricing=ProviderPricing(0.5, PRICE_SOURCE),
    )
    qdrant = QdrantIndex(
        url=str(env["DEEPRESEARCH_QDRANT_URL"]),
        api_key=str(env.get("DEEPRESEARCH_QDRANT_API_KEY") or ""),
        collection=str(env["DEEPRESEARCH_QDRANT_COLLECTION"]),
    )
    lexical = StorageLexicalBackend(store=store)
    dense = QdrantDenseBackend(store=store, index=qdrant, embedding=embedding)
    all_questions = json.loads(questions.read_text(encoding="utf-8"))
    selected = [item for item in all_questions if item["split"] == split and item["question_type"] != "refusal"]
    spans_cache: dict[str, list[ChunkSpan]] = {}
    rows: list[dict[str, Any]] = []
    for item in selected:
        as_of = str(item["as_of"])
        if as_of not in spans_cache:
            spans_cache[as_of] = [
                ChunkSpan(chunk.id, chunk.document_version_id, chunk.char_start, chunk.char_end)
                for chunk in store.list_ready_chunks(as_of=as_of)
            ]
        filters = RetrievalFilter(as_of=date.fromisoformat(as_of), index_version=index_version)
        sparse = lexical.search(query=item["question"], filters=filters, limit=TOP_K)
        dense_hits = dense.search(query=item["question"], filters=filters, limit=TOP_K)
        sources = {chunk.chunk_id: chunk for chunk in [*sparse, *dense_hits]}
        fused = rrf_fuse(
            lexical_ids=[chunk.chunk_id for chunk in sparse],
            dense_ids=[chunk.chunk_id for chunk in dense_hits],
            texts={identifier: chunk.text for identifier, chunk in sources.items()},
            top_k=TOP_K,
            lexical_scores={chunk.chunk_id: chunk.score for chunk in sparse if chunk.score is not None},
            dense_scores={chunk.chunk_id: chunk.score for chunk in dense_hits if chunk.score is not None},
        )
        reranked = reranker.rerank(item["question"], fused, RERANK_TOP_N)
        relevant = resolve_labels_to_chunks(
            [SpanLabel(**label) for label in item["labels"]], spans_cache[as_of]
        )
        rrf_ids = [candidate.chunk_id for candidate in fused]
        rerank_ids = [candidate.chunk_id for candidate in reranked.candidates]
        rows.append(
            {
                "id": item["id"],
                "question_type": item["question_type"],
                "relevant_chunks": len(relevant),
                "recall_at_20": recall_at_k(rrf_ids, relevant, 20),
                "rrf_ndcg_at_10": ndcg_at_k(rrf_ids, relevant, 10),
                "rerank_ndcg_at_10": ndcg_at_k(rerank_ids, relevant, 10),
                "lexical_count": len(sparse),
                "dense_count": len(dense_hits),
                "fused_count": len(fused),
                "rerank_count": len(reranked.candidates),
            }
        )
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_type[str(row["question_type"])].append(row)
    result = {
        "schema_version": 1,
        "split": split,
        "index_version": index_version,
        "parameters": {"rrf_top_k": TOP_K, "rerank_top_n": RERANK_TOP_N},
        "questions": len(rows),
        "metrics": {
            "recall_at_20": _mean([row["recall_at_20"] for row in rows]),
            "rrf_ndcg_at_10": _mean([row["rrf_ndcg_at_10"] for row in rows]),
            "rerank_ndcg_at_10": _mean([row["rerank_ndcg_at_10"] for row in rows]),
            "zero_relevant": sum(row["relevant_chunks"] == 0 for row in rows),
        },
        "metrics_by_question_type": {
            kind: {
                "questions": len(values),
                "recall_at_20": _mean([row["recall_at_20"] for row in values]),
                "rerank_ndcg_at_10": _mean([row["rerank_ndcg_at_10"] for row in values]),
            }
            for kind, values in sorted(by_type.items())
        },
        "per_question": rows,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--questions", required=True, type=Path)
    parser.add_argument("--split", required=True)
    parser.add_argument("--index-version", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--budget-cny", type=float, default=10.0)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    args = parser.parse_args()
    result = evaluate(
        database=args.database,
        questions=args.questions,
        split=args.split,
        index_version=args.index_version,
        output=args.output,
        budget_cny=args.budget_cny,
        env=dotenv_values(args.env_file),
    )
    print(json.dumps(result["metrics"], ensure_ascii=False))


if __name__ == "__main__":
    main()
