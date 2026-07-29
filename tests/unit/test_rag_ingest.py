from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from deepresearch_agent.rag.ingest import ingest_and_persist, ingest_corpus
from deepresearch_agent.storage import SQLiteStore


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
        self.assertEqual(repeated.superseded_chunks, 0)
        self.assertGreater(changed.superseded_chunks, 0)
        self.assertEqual(status["active_chunks"], changed.chunks)
        self.assertEqual(status["superseded_chunks"], changed.superseded_chunks)


if __name__ == "__main__":
    unittest.main()
