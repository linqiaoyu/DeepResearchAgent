"""Rebuild a Qdrant-derived RAG index from authoritative SQLite chunks.

The command deliberately keeps the source store authoritative: Qdrant receives
only vectors and locating payloads, and every provider call settles through the
shared LLM ledger.  A checkpoint records completed chunk IDs after a successful
Qdrant upsert, so restarting the same index version does not repay completed
batches.
"""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path

from dotenv import dotenv_values

from deepresearch_agent.llm import LLMClient
from deepresearch_agent.rag.chunking import CHUNKER_VERSION
from deepresearch_agent.rag.qdrant_index import IndexedChunk, QdrantIndex
from deepresearch_agent.rag.retrieval import DashScopeEmbeddingProvider, ProviderPricing
from deepresearch_agent.storage import SQLiteStore


@dataclass(frozen=True)
class RebuildReport:
    index_version: str
    active_chunks: int
    indexed_chunks: int
    skipped_from_checkpoint: int
    dropped_unresolvable: int
    embedding_calls: int
    elapsed_seconds: float


def _load_checkpoint(path: Path, index_version: str) -> set[str]:
    if not path.exists():
        return set()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("index_version") != index_version:
        raise ValueError("checkpoint index_version differs; use a new checkpoint path")
    completed = payload.get("completed_chunk_ids")
    if not isinstance(completed, list) or not all(isinstance(item, str) for item in completed):
        raise ValueError("checkpoint completed_chunk_ids is invalid")
    return set(completed)


def _save_checkpoint(path: Path, index_version: str, completed: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"index_version": index_version, "completed_chunk_ids": sorted(completed)},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _batches[T](items: list[T], size: int) -> list[list[T]]:
    return [items[offset : offset + size] for offset in range(0, len(items), size)]


def rebuild(
    *,
    database: Path,
    env: dict[str, str | None],
    checkpoint: Path,
    output: Path,
    index_version: str,
    dimensions: int,
    chunks_per_batch: int,
    embedding_concurrency: int,
    budget_cny: float,
) -> RebuildReport:
    if chunks_per_batch < 1 or chunks_per_batch > 10:
        raise ValueError("chunks_per_batch must be in 1..10, matching the verified provider limit")
    if embedding_concurrency < 1:
        raise ValueError("embedding_concurrency must be positive")
    required = ("DASHSCOPE_API_KEY", "DEEPRESEARCH_QDRANT_URL", "DEEPRESEARCH_QDRANT_COLLECTION")
    missing = [name for name in required if not (env.get(name) or "").strip()]
    if missing:
        raise ValueError(f"missing configured values: {', '.join(missing)}")
    started = time.monotonic()
    store = SQLiteStore(database)
    chunks = store.list_ready_chunks(as_of="9999-12-31")
    completed = _load_checkpoint(checkpoint, index_version)
    pending = [chunk for chunk in chunks if chunk.id not in completed]
    ledger = LLMClient(
        ledger_path=output.with_name("index_ledger.jsonl"),
        global_ledger_path=Path("data/runtime/llm_ledger.jsonl"),
        budget_cny=budget_cny,
        completion_func=lambda **_: {},
    )
    run_id = f"047-index-{index_version}"
    ledger.start_run(run_id)
    embedding = DashScopeEmbeddingProvider(
        api_key=str(env["DASHSCOPE_API_KEY"]),
        ledger=ledger,
        run_id=run_id,
        pricing=ProviderPricing(0.5, "aliyun_model_studio_public_20260729"),
        dimensions=dimensions,
        max_batch_size=chunks_per_batch,
    )
    index = QdrantIndex(
        url=str(env["DEEPRESEARCH_QDRANT_URL"]),
        api_key=str(env.get("DEEPRESEARCH_QDRANT_API_KEY") or ""),
        collection=str(env["DEEPRESEARCH_QDRANT_COLLECTION"]),
    )
    embedded = 0
    batches = _batches(pending, chunks_per_batch)

    def embed_batch(batch: list[object]) -> list[list[float]]:
        return embedding.embed([getattr(chunk, "content") for chunk in batch])

    with ThreadPoolExecutor(max_workers=embedding_concurrency) as executor:
        for offset in range(0, len(batches), embedding_concurrency):
            window = batches[offset : offset + embedding_concurrency]
            futures = [(batch, executor.submit(embed_batch, batch)) for batch in window]
            for batch, future in futures:
                vectors = future.result()
                if len(vectors) != len(batch):
                    raise RuntimeError("embedding provider returned an incomplete batch")
                index.upsert(
                    chunks=[
                        IndexedChunk(
                            chunk_id=chunk.id,
                            document_version_id=chunk.document_version_id,
                            effective_date=chunk.effective_date,
                            char_start=chunk.char_start,
                            char_end=chunk.char_end,
                            vector=vector,
                        )
                        for chunk, vector in zip(batch, vectors, strict=True)
                    ],
                    model="text-embedding-v4",
                    chunker_version=CHUNKER_VERSION,
                    index_version=index_version,
                )
                completed.update(chunk.id for chunk in batch)
                _save_checkpoint(checkpoint, index_version, completed)
                embedded += len(batch)
    report = RebuildReport(
        index_version=index_version,
        active_chunks=len(chunks),
        indexed_chunks=embedded,
        skipped_from_checkpoint=len(chunks) - len(pending),
        dropped_unresolvable=0,
        embedding_calls=(len(pending) + chunks_per_batch - 1) // chunks_per_batch,
        elapsed_seconds=round(time.monotonic() - started, 3),
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(asdict(report), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--index-version", required=True)
    parser.add_argument("--dimensions", type=int, default=1024)
    parser.add_argument("--chunks-per-batch", type=int, default=10)
    parser.add_argument("--embedding-concurrency", type=int, default=1)
    parser.add_argument("--budget-cny", type=float, default=50.0)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    args = parser.parse_args()
    result = rebuild(
        database=args.database,
        env=dotenv_values(args.env_file),
        checkpoint=args.checkpoint,
        output=args.output,
        index_version=args.index_version,
        dimensions=args.dimensions,
        chunks_per_batch=args.chunks_per_batch,
        embedding_concurrency=args.embedding_concurrency,
        budget_cny=args.budget_cny,
    )
    print(json.dumps(asdict(result), ensure_ascii=False))


if __name__ == "__main__":
    main()
