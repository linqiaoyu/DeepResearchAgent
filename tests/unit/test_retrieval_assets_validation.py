from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _load_script(name: str):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validator = _load_script("validate_retrieval_assets.py")
downloader = _load_script("download_corpus_finance_v1.py")


class RetrievalAssetsValidationTests(unittest.TestCase):
    def _assets(self, root: Path) -> tuple[Path, Path, Path, Path]:
        source = root / "raw"
        source.mkdir()
        documents = []
        versions: list[str] = []
        for index in range(60):
            path = f"issuer_{index:02d}.txt"
            text = f"第{index}份正式原文 12345678"
            encoded = text.encode("utf-8")
            (source / path).write_bytes(encoded)
            url = f"https://www.sec.gov/Archives/edgar/data/100{index}/annual-{index}.html"
            sha = hashlib.sha256(encoded).hexdigest()
            documents.append({
                "path": path,
                "url": url,
                "sha256": sha,
                "bytes": len(encoded),
                "retrieved_at": "2026-07-29T00:00:00Z",
                "public_accessibility": "public original",
                "effective_date": f"202{2 + index % 3}-12-31",
            })
            versions.append(validator.document_version_id(url, sha))
        corpus = root / "corpus.json"
        payload = {"schema_version": 1, "documents": documents}
        corpus.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        questions, audit = [], []
        def add(question_type: str, labels: list[dict[str, object]], split: str) -> None:
            question_id = f"R{len(questions) + 1:03d}"
            questions.append({"id": question_id, "question": f"中文问题 {question_id}", "as_of": "2025-12-31", "question_type": question_type, "split": split, "labels": labels})
            for label in labels:
                index = versions.index(label["document_version_id"])
                audit.append({"question_id": question_id, "document_version_id": label["document_version_id"], "canonical_url": documents[index]["url"], "page_number": None, "char_start": 0, "char_end": len(f"第{index}份正式原文 12345678"), "source_excerpt": f"第{index}份正式原文 12345678", "relevance": 2})
        for index in range(20):
            add("numeric", [{"document_version_id": versions[index], "char_start": 0, "char_end": len(f"第{index}份正式原文 12345678"), "relevance": 2}], "dev")
        for index in range(15):
            add("cross_period", [{"document_version_id": versions[index], "char_start": 0, "char_end": len(f"第{index}份正式原文 12345678"), "relevance": 2}, {"document_version_id": versions[index + 20], "char_start": 0, "char_end": len(f"第{index + 20}份正式原文 12345678"), "relevance": 2}], "dev" if index < 4 else "test")
        for index in range(15):
            doc = index + 35
            add("table", [{"document_version_id": versions[doc], "char_start": 0, "char_end": len(f"第{doc}份正式原文 12345678"), "relevance": 2}], "test")
        for _ in range(10):
            question_id = f"R{len(questions) + 1:03d}"
            questions.append({"id": question_id, "question": "中文问题：2025 年经审计营业收入", "as_of": "2025-12-31", "question_type": "refusal", "split": "test", "expected_behavior": "refuse_insufficient_evidence", "labels": []})
            audit.append({"question_id": question_id, "document_version_id": None, "canonical_url": None, "page_number": None, "char_start": None, "char_end": None, "source_excerpt": None, "relevance": None})
        golden = root / "golden"
        golden.mkdir()
        questions_path = golden / "questions.json"
        questions_path.write_text(json.dumps(questions, ensure_ascii=False), encoding="utf-8")
        (golden / "annotation_audit.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in audit), encoding="utf-8")
        meta = root / "meta.json"
        meta.write_text(json.dumps({"corpus_fingerprint": validator.corpus_fingerprint(payload), "corpus_document_count": 60, "question_count": 60}), encoding="utf-8")
        return source, corpus, questions_path, meta

    def test_valid_assets_and_mutated_span_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source, corpus, questions, meta = self._assets(Path(directory))
            report = validator.validate_assets(input_dir=source, corpus_path=corpus, questions_path=questions, meta_path=meta)
            self.assertEqual(report["resolved_labels"], 65)
            payload = json.loads(questions.read_text(encoding="utf-8"))
            payload[0]["labels"][0]["char_end"] = 999999
            questions.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "char range exceeds"):
                validator.validate_assets(input_dir=source, corpus_path=corpus, questions_path=questions, meta_path=meta)

    def test_download_boundary_rejects_disguised_pdf_and_captcha(self) -> None:
        self.assertEqual(
            downloader._is_original_response(path=Path("annual.pdf"), data=b"<html>not pdf</html>", content_type="text/html"),
            "html_or_non_pdf_disguised_as_pdf",
        )
        self.assertEqual(
            downloader._is_original_response(path=Path("annual.html"), data=b"<html>captcha</html>", content_type="text/html"),
            "blocked_or_captcha_response",
        )


if __name__ == "__main__":
    unittest.main()
