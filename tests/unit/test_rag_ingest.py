from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from deepresearch_agent.rag.ingest import ingest_and_persist, ingest_corpus
from deepresearch_agent.storage import SQLiteStore, StoredChunk


class RagIngestTests(unittest.TestCase):
    def _manifest(self, path: Path, text: str) -> dict[str, object]:
        encoded = text.encode("utf-8")
        return {
            "documents": [{
                "path": path.name,
                "url": "https://example.test/document",
                "sha256": hashlib.sha256(encoded).hexdigest(),
                "bytes": len(encoded),
                "retrieved_at": "2026-07-29T00:00:00Z",
                "public_accessibility": "public",
                "effective_date": "2025-12-31",
            }]
        }

    def test_ingest_is_deterministic_and_all_chunks_are_located(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "report.txt"
            text = "a" * 3000
            source.write_text(text, encoding="utf-8")
            manifest = root / "corpus.json"
            manifest.write_text(json.dumps(self._manifest(source, text)), encoding="utf-8")

            first = ingest_corpus(input_dir=root, corpus_path=manifest)
            second = ingest_corpus(input_dir=root, corpus_path=manifest)

        self.assertEqual([item.id for item in first], [item.id for item in second])
        self.assertTrue(all(item.char_end > item.char_start for item in first))
        self.assertTrue(all(item.effective_date == "2025-12-31" for item in first))

    def test_ingest_rejects_manifest_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "report.txt"
            source.write_text("actual", encoding="utf-8")
            manifest = root / "corpus.json"
            manifest.write_text(json.dumps(self._manifest(source, "expected")), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "integrity mismatch"):
                ingest_corpus(input_dir=root, corpus_path=manifest)

    def test_persisted_versions_are_idempotent_then_superseded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "report.txt"
            first_text = "a" * 3000
            source.write_text(first_text, encoding="utf-8")
            manifest = root / "corpus.json"
            manifest.write_text(json.dumps(self._manifest(source, first_text)), encoding="utf-8")
            store = SQLiteStore(root / "research.db")

            first = ingest_and_persist(input_dir=root, corpus_path=manifest, store=store)
            repeated = ingest_and_persist(input_dir=root, corpus_path=manifest, store=store)

            second_text = "b" * 3000
            source.write_text(second_text, encoding="utf-8")
            manifest.write_text(json.dumps(self._manifest(source, second_text)), encoding="utf-8")
            changed = ingest_and_persist(input_dir=root, corpus_path=manifest, store=store)

            status = store.rag_status()
        self.assertEqual(first.superseded_chunks, 0)
        self.assertGreater(first.added_chunks, 0)
        self.assertEqual(first.removed_chunks, 0)
        self.assertEqual(repeated.superseded_chunks, 0)
        self.assertEqual(repeated.added_chunks, 0)
        self.assertEqual(repeated.removed_chunks, 0)
        self.assertGreater(changed.superseded_chunks, 0)
        self.assertEqual(status["active_chunks"], changed.chunks)
        self.assertEqual(status["superseded_chunks"], changed.superseded_chunks)

    def test_reingest_replaces_stale_derived_chunk_layout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteStore(Path(directory) / "research.db")
            first = StoredChunk(
                id="old-layout",
                char_start=0,
                char_end=3,
                page_number=None,
                effective_date="2025-12-31",
                content="old",
            )
            replacement = StoredChunk(
                id="new-layout",
                char_start=0,
                char_end=6,
                page_number=None,
                effective_date="2025-12-31",
                content="newest",
            )
            store.record_document_version(
                canonical_url="https://example.test/document",
                file_sha256="a" * 64,
                effective_date="2025-12-31",
                chunks=[first],
            )
            store.record_document_version(
                canonical_url="https://example.test/document",
                file_sha256="a" * 64,
                effective_date="2025-12-31",
                chunks=[replacement],
            )
            chunks = store.list_ready_chunks(as_of="2025-12-31")

        self.assertEqual([chunk.id for chunk in chunks], ["new-layout"])

    def test_storage_rejects_invalid_chunk_location_mutations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteStore(Path(directory) / "research.db")
            for name, chunk, message in (
                (
                    "file_hash",
                    StoredChunk("bad-hash", 0, 4, None, "2025-12-31", "text"),
                    "SHA-256",
                ),
                (
                    "char_range",
                    StoredChunk("bad-range", 5, 5, None, "2025-12-31", "text"),
                    "character ranges",
                ),
                (
                    "page",
                    StoredChunk("bad-page", 0, 4, 0, "2025-12-31", "text"),
                    "page numbers",
                ),
            ):
                with self.subTest(mutation=name), self.assertRaisesRegex(ValueError, message):
                    store.record_document_version(
                        canonical_url=f"https://example.test/{name}",
                        file_sha256=("invalid" if name == "file_hash" else ("b" * 64 if name == "char_range" else "c" * 64)),
                        effective_date="2025-12-31",
                        chunks=[chunk],
                    )


if __name__ == "__main__":
    unittest.main()
