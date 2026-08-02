"""Backfill Qdrant's filter-only entity payload from authoritative chunks.

This operation sends stable point IDs and entity identifiers only. It does not
read source text into Qdrant, invoke an embedding provider, or create a second
budget ledger.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

from dotenv import dotenv_values

from deepresearch_agent.llm_config import DASHSCOPE_EMBEDDING_MODEL
from deepresearch_agent.rag.chunking import CHUNKER_VERSION
from deepresearch_agent.rag.qdrant_index import QdrantIndex
from deepresearch_agent.storage import SQLiteStore


def backfill(
    *, database: Path, env: dict[str, str | None], batch_size: int, index_version: str
) -> dict[str, int]:
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    required = ("DEEPRESEARCH_QDRANT_URL", "DEEPRESEARCH_QDRANT_COLLECTION")
    missing = [name for name in required if not (env.get(name) or "").strip()]
    if missing:
        raise ValueError(f"missing configured values: {', '.join(missing)}")
    chunks = SQLiteStore(database).list_ready_chunks(as_of="9999-12-31")
    if not chunks or any(not chunk.entity_id for chunk in chunks):
        raise ValueError("all ready authoritative chunks must have an entity_id")
    index = QdrantIndex(
        url=str(env["DEEPRESEARCH_QDRANT_URL"]),
        api_key=str(env.get("DEEPRESEARCH_QDRANT_API_KEY") or ""),
        collection=str(env["DEEPRESEARCH_QDRANT_COLLECTION"]),
    )
    index.ensure_collection(dimensions=1024, index_version=index_version)
    grouped: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for chunk in chunks:
        grouped[(chunk.entity_id, chunk.effective_date[:4], chunk.published_at)].append(chunk.id)
    updated = 0
    for (entity_id, period_label, published_at), chunk_ids in sorted(grouped.items()):
        for offset in range(0, len(chunk_ids), batch_size):
            updated += index.set_filter_payload(
                chunk_ids=chunk_ids[offset : offset + batch_size],
                payload={"entity_id": entity_id, "period_label": period_label, "published_at": published_at},
                model=DASHSCOPE_EMBEDDING_MODEL,
                chunker_version=CHUNKER_VERSION,
            )
    return {
        "active_chunks": len(chunks),
        "entity_period_groups": len(grouped),
        "updated_points": updated,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--index-version", required=True)
    args = parser.parse_args()
    print(
        backfill(
            database=args.database,
            env=dotenv_values(args.env_file),
            batch_size=args.batch_size,
            index_version=args.index_version,
        )
    )


if __name__ == "__main__":
    main()
