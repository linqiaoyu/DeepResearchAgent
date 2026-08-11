"""Measure ingestion idempotency, provenance, withholding, and index fail-closed."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from typing import Any
from unittest.mock import patch

from deepresearch_agent.rag.ingest import ingest_and_persist
from deepresearch_agent.rag.qdrant_index import IndexedChunk, QdrantIndex
from deepresearch_agent.storage import SQLiteStore


class _Response:
    def __init__(self, status_code: int, payload: dict[str, object] | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http={self.status_code}")

    def json(self) -> dict[str, object]:
        return self._payload


def _manifest(path: Path, text: str, *, published: bool) -> dict[str, object]:
    encoded = text.encode("utf-8")
    document: dict[str, object] = {
        "path": path.name,
        "url": "https://example.test/report",
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "bytes": len(encoded),
        "retrieved_at": "2026-08-11T00:00:00Z",
        "public_accessibility": "public",
        "effective_date": "2025-12-31",
    }
    if published:
        document.update(
            {
                "published_at": "2026-04-01",
                "published_at_source": "exchange_registry",
            }
        )
    return {"documents": [document]}


def _indexed(*, published_at: str = "2026-04-01", version: str = "idx-v1") -> IndexedChunk:
    return IndexedChunk(
        chunk_id="chunk-1",
        document_version_id="document-version-1",
        effective_date="2025-12-31",
        char_start=0,
        char_end=10,
        vector=[0.1, 0.2],
        source_url="https://example.test/report",
        published_at=published_at,
        published_at_source="exchange_registry",
        index_version=version,
    )


def measure() -> dict[str, int | float]:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "issuer_report.txt"
        source.write_text("authoritative filing text", encoding="utf-8")
        manifest = root / "corpus.json"
        manifest.write_text(
            json.dumps(_manifest(source, source.read_text(encoding="utf-8"), published=True)),
            encoding="utf-8",
        )
        store = SQLiteStore(root / "rag.db")
        ingest_and_persist(input_dir=root, corpus_path=manifest, store=store)
        repeated = ingest_and_persist(input_dir=root, corpus_path=manifest, store=store)

        undated_source = root / "undated_report.txt"
        undated_source.write_text("undated filing text", encoding="utf-8")
        undated_manifest = root / "undated.json"
        undated_manifest.write_text(
            json.dumps(
                _manifest(
                    undated_source,
                    undated_source.read_text(encoding="utf-8"),
                    published=False,
                )
            ),
            encoding="utf-8",
        )
        undated_store = SQLiteStore(root / "undated.db")
        undated_report = ingest_and_persist(
            input_dir=root,
            corpus_path=undated_manifest,
            store=undated_store,
        )
        undated_visible = len(
            undated_store.list_ready_chunks(as_of="9999-12-31")
        )

    index = QdrantIndex(
        url="https://qdrant.test",
        api_key="test",
        collection="collection",
    )
    known = _indexed()
    unknown = _indexed(published_at="")
    with patch(
        "deepresearch_agent.rag.qdrant_index.httpx.get",
        return_value=_Response(404),
    ), patch(
        "deepresearch_agent.rag.qdrant_index.httpx.put",
        side_effect=[_Response(200)] * 7,
    ) as put:
        first_written = index.upsert(
            chunks=[known, unknown],
            model="embedding-model",
            chunker_version="chunker-v1",
            index_version="idx-v1",
        )
        first_points = put.call_args_list[5].kwargs["json"]["points"]
        second_written = index.upsert(
            chunks=[known],
            model="embedding-model",
            chunker_version="chunker-v1",
            index_version="idx-v1",
        )
        second_points = put.call_args_list[6].kwargs["json"]["points"]
    payload = first_points[0]["payload"]
    required = {
        "document_version_id",
        "source_url",
        "published_at_source",
        "index_version",
    }

    mismatch_rejected = 0
    mismatch_index = QdrantIndex(
        url="https://qdrant.test",
        api_key="test",
        collection="collection",
    )
    with patch("deepresearch_agent.rag.qdrant_index.httpx.get") as get:
        try:
            mismatch_index.upsert(
                chunks=[_indexed(version="idx-old")],
                model="embedding-model",
                chunker_version="chunker-v1",
                index_version="idx-new",
            )
        except ValueError:
            mismatch_rejected = int(get.call_count == 0)

    return {
        "indexed_chunk_provenance_rate": len(required & set(payload)) / len(required),
        "repeat_ingest_added_chunks": repeated.added_chunks,
        "repeat_ingest_removed_chunks": repeated.removed_chunks,
        "undated_visible_documents": undated_visible,
        "undated_withheld_documents": undated_report.substituted_disclosure_documents,
        "unknown_vector_chunks_written": first_written - 1,
        "stable_point_id_match": float(
            first_points[0]["id"] == second_points[0]["id"]
        ),
        "repeat_vector_upsert_count": second_written,
        "index_version_mismatch_rejected_before_http": mismatch_rejected,
    }


def evaluate(metrics: dict[str, Any]) -> list[str]:
    expected = {
        "indexed_chunk_provenance_rate": 1.0,
        "repeat_ingest_added_chunks": 0,
        "repeat_ingest_removed_chunks": 0,
        "undated_visible_documents": 0,
        "undated_withheld_documents": 1,
        "unknown_vector_chunks_written": 0,
        "stable_point_id_match": 1.0,
        "repeat_vector_upsert_count": 1,
        "index_version_mismatch_rejected_before_http": 1,
    }
    return [
        f"{name}: expected {wanted}, got {metrics.get(name)}"
        for name, wanted in expected.items()
        if metrics.get(name) != wanted
    ]


def _self_test(metrics: dict[str, Any]) -> None:
    if evaluate(metrics):
        raise SystemExit("rag_ingestion_self_test=FAIL production probe is dirty")
    cases = {
        "missing_provenance": {**metrics, "indexed_chunk_provenance_rate": 0.75},
        "non_idempotent": {**metrics, "repeat_ingest_added_chunks": 1},
        "undated_visible": {**metrics, "undated_visible_documents": 1},
        "vector_fallback": {**metrics, "unknown_vector_chunks_written": 1},
        "unstable_point": {**metrics, "stable_point_id_match": 0.0},
        "version_mismatch_allowed": {
            **metrics,
            "index_version_mismatch_rejected_before_http": 0,
        },
    }
    for label, broken in cases.items():
        if not evaluate(broken):
            raise SystemExit(f"rag_ingestion_self_test=FAIL accepted {label}")
    print(f"rag_ingestion_self_test=PASS cases={len(cases) + 1}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    metrics = measure()
    if args.self_test:
        _self_test(metrics)
    print(json.dumps(metrics, sort_keys=True))
    failures = evaluate(metrics)
    if failures:
        print("\n".join(failures), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
