from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "rebuild_rag_index.py"
SPEC = importlib.util.spec_from_file_location("rebuild_rag_index", SCRIPT)
assert SPEC and SPEC.loader
rebuild_rag_index = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = rebuild_rag_index
SPEC.loader.exec_module(rebuild_rag_index)


def _chunk(number: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=f"chunk-{number}",
        document_version_id="document-version-1",
        canonical_url="https://example.test/document",
        effective_date="2025-12-31",
        published_at="2026-04-01",
        char_start=number * 10,
        char_end=number * 10 + 9,
        content=f"authoritative chunk {number}",
    )


class _Store:
    def __init__(self, _: Path, chunks: list[SimpleNamespace]) -> None:
        self._chunks = chunks

    def list_ready_chunks(self, *, as_of: str) -> list[SimpleNamespace]:
        assert as_of == "9999-12-31"
        return self._chunks


class _Ledger:
    def __init__(self, **_: object) -> None:
        pass

    def start_run(self, _: str) -> None:
        pass


class _Embedding:
    def __init__(self, *, failure: BaseException | None = None, **_: object) -> None:
        self.failure = failure

    def embed(self, texts: list[str]) -> list[list[float]]:
        if self.failure is not None:
            raise self.failure
        return [[float(index), 1.0] for index, _ in enumerate(texts)]


class RagIndexRebuildRecoveryTests(unittest.TestCase):
    def _run(
        self,
        root: Path,
        *,
        chunks: list[SimpleNamespace],
        embedding: _Embedding,
        index: object,
    ) -> object:
        with (
            mock.patch.object(rebuild_rag_index, "SQLiteStore", side_effect=lambda path: _Store(path, chunks)),
            mock.patch.object(rebuild_rag_index, "LLMClient", _Ledger),
            mock.patch.object(rebuild_rag_index, "DashScopeEmbeddingProvider", lambda **_: object()),
            mock.patch.object(rebuild_rag_index, "CachedEmbeddingProvider", lambda **_: embedding),
            mock.patch.object(rebuild_rag_index, "QdrantIndex", lambda **_: index),
        ):
            return rebuild_rag_index.rebuild(
                database=root / "authoritative.db",
                env={
                    "DASHSCOPE_API_KEY": "configured-for-test",
                    "DEEPRESEARCH_QDRANT_URL": "https://qdrant.invalid",
                    "DEEPRESEARCH_QDRANT_COLLECTION": "recovery-test",
                },
                checkpoint=root / "checkpoint.json",
                output=root / "report.json",
                index_version="recovery-v1",
                dimensions=2,
                chunks_per_batch=2,
                embedding_concurrency=1,
                budget_cny=1.0,
            )

    @staticmethod
    def _checkpoint(root: Path) -> set[str]:
        path = root / "checkpoint.json"
        if not path.exists():
            return set()
        return set(json.loads(path.read_text(encoding="utf-8"))["completed_chunk_ids"])

    def test_network_failure_is_explicit_and_does_not_mark_chunks_index_ready(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            index = mock.Mock()
            with self.assertRaisesRegex(ConnectionError, "network unavailable"):
                self._run(
                    root,
                    chunks=[_chunk(1)],
                    embedding=_Embedding(failure=ConnectionError("network unavailable")),
                    index=index,
                )

            self.assertEqual(self._checkpoint(root), set())
            index.upsert.assert_not_called()

    def test_rate_limit_failure_is_explicit_and_does_not_mark_chunks_index_ready(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            index = mock.Mock()
            with self.assertRaisesRegex(RuntimeError, "429"):
                self._run(
                    root,
                    chunks=[_chunk(1)],
                    embedding=_Embedding(failure=RuntimeError("429 rate limited")),
                    index=index,
                )

            self.assertEqual(self._checkpoint(root), set())
            index.upsert.assert_not_called()

    def test_qdrant_timeout_is_explicit_and_does_not_mark_embedded_chunks_ready(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            index = mock.Mock()
            index.upsert.side_effect = TimeoutError("qdrant timeout")
            with self.assertRaisesRegex(TimeoutError, "qdrant timeout"):
                self._run(root, chunks=[_chunk(1)], embedding=_Embedding(), index=index)

            self.assertEqual(self._checkpoint(root), set())
            index.upsert.assert_called_once()

    def test_partial_batch_failure_checkpoints_only_confirmed_batches_then_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            chunks = [_chunk(number) for number in range(1, 5)]
            failing_index = mock.Mock()
            failing_index.upsert.side_effect = [2, TimeoutError("second batch timeout")]
            with self.assertRaisesRegex(TimeoutError, "second batch timeout"):
                self._run(root, chunks=chunks, embedding=_Embedding(), index=failing_index)

            self.assertEqual(self._checkpoint(root), {"chunk-1", "chunk-2"})
            recovery_index = mock.Mock()
            result = self._run(root, chunks=chunks, embedding=_Embedding(), index=recovery_index)

            self.assertEqual(result.indexed_chunks, 2)
            self.assertEqual(result.skipped_from_checkpoint, 2)
            self.assertEqual(self._checkpoint(root), {"chunk-1", "chunk-2", "chunk-3", "chunk-4"})
            recovered = recovery_index.upsert.call_args.kwargs["chunks"]
            self.assertEqual([chunk.chunk_id for chunk in recovered], ["chunk-3", "chunk-4"])


if __name__ == "__main__":
    unittest.main()
