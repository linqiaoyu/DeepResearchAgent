"""Validate the frozen finance_v1 corpus and retrieval_v1 span annotations."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse
from uuid import NAMESPACE_URL, uuid5

from deepresearch_agent.rag.ingest import _extract, ingest_corpus, load_corpus


def corpus_fingerprint(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def document_version_id(url: str, file_sha256: str) -> str:
    document_id = str(uuid5(NAMESPACE_URL, url))
    return str(uuid5(NAMESPACE_URL, f"{document_id}:{file_sha256}"))


def _global_text(path: Path) -> str:
    sections = _extract(path)
    value = ""
    for section in sections:
        if len(value) < section.char_start:
            value += "\n" * (section.char_start - len(value))
        value += section.text
    return value


def _fail(message: str) -> None:
    raise ValueError(message)


def _load_audit(questions_path: Path) -> list[dict[str, object]]:
    audit_path = questions_path.with_name("annotation_audit.jsonl")
    if not audit_path.is_file():
        _fail(f"annotation audit missing: {audit_path}")
    rows: list[dict[str, object]] = []
    for line_number, line in enumerate(audit_path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            _fail(f"invalid audit JSONL line {line_number}: {error}")
        if not isinstance(value, dict):
            _fail(f"invalid audit row {line_number}")
        rows.append(value)
    return rows


def validate_assets(*, input_dir: Path, corpus_path: Path, questions_path: Path, meta_path: Path) -> dict[str, int | str]:
    raw_manifest = json.loads(corpus_path.read_text(encoding="utf-8"))
    if not isinstance(raw_manifest, dict) or raw_manifest.get("schema_version") != 1:
        _fail("corpus schema_version must be 1")
    documents = raw_manifest.get("documents")
    if not isinstance(documents, list) or len(documents) < 60:
        _fail("documents must contain at least 60 entries")
    paths = [entry.get("path") for entry in documents if isinstance(entry, dict)]
    urls = [entry.get("url") for entry in documents if isinstance(entry, dict)]
    hashes = [entry.get("sha256") for entry in documents if isinstance(entry, dict)]
    if len(paths) != len(set(paths)) or len(urls) != len(set(urls)) or len(hashes) != len(set(hashes)):
        _fail("corpus paths, URLs, and SHA256 values must each be unique")
    for entry in documents:
        if not isinstance(entry, dict):
            _fail("corpus document is not an object")
        url = entry.get("url")
        if not isinstance(url, str) or urlparse(url).scheme != "https" or "search" in url.lower():
            _fail("corpus URL must be a canonical HTTPS original, not a search page")
        path = entry.get("path")
        if not isinstance(path, str) or Path(path).is_absolute() or ".." in Path(path).parts:
            _fail("corpus path must be a safe relative path")
        target = input_dir / path
        if not target.is_file():
            _fail(f"manifest document missing: {path}")
        raw = target.read_bytes()
        if len(raw) != entry.get("bytes") or hashlib.sha256(raw).hexdigest() != entry.get("sha256"):
            _fail(f"manifest integrity mismatch: {path}")
    manifest = load_corpus(corpus_path)
    texts = {path: _global_text(input_dir / path) for path in manifest}
    version_to_entry = {
        document_version_id(entry.url, entry.sha256): (path, entry)
        for path, entry in manifest.items()
    }
    questions = json.loads(questions_path.read_text(encoding="utf-8"))
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if not isinstance(questions, list) or len(questions) != 60:
        _fail("questions must contain exactly 60 entries")
    if meta.get("corpus_fingerprint") != corpus_fingerprint(raw_manifest):
        _fail("corpus fingerprint does not match meta")
    if meta.get("corpus_document_count") != len(documents) or meta.get("question_count") != 60:
        _fail("meta document or question count does not match frozen assets")
    ids = [question.get("id") for question in questions if isinstance(question, dict)]
    if len(ids) != 60 or len(ids) != len(set(ids)):
        _fail("question IDs must be unique")
    splits = Counter(question.get("split") for question in questions)
    if splits != Counter({"dev": 24, "test": 36}):
        _fail("splits must be dev=24 and test=36")
    types = Counter(question.get("question_type") for question in questions)
    if types["numeric"] + types["table"] < 20 or types["cross_period"] < 15 or types["refusal"] < 10:
        _fail("question type minimums are not satisfied")
    chinese = sum(bool(re.search(r"[\u3400-\u9fff]", str(question.get("question", "")))) for question in questions)
    if chinese < 40:
        _fail("fewer than 40 Chinese questions")
    audit = _load_audit(questions_path)
    audits_by_question: dict[str, list[dict[str, object]]] = {}
    for row in audit:
        question_id = row.get("question_id")
        if not isinstance(question_id, str):
            _fail("audit row lacks question_id")
        audits_by_question.setdefault(question_id, []).append(row)
    all_chunks = ingest_corpus(input_dir=input_dir, corpus_path=corpus_path)
    chunks_by_version: dict[str, list[tuple[int, int]]] = {}
    for chunk in all_chunks:
        version = document_version_id_for_hash(version_to_entry, chunk.document_sha256)
        chunks_by_version.setdefault(version, []).append((chunk.char_start, chunk.char_end))
    span_labels = resolved_labels = 0
    for question in questions:
        if not isinstance(question, dict):
            _fail("question is not an object")
        question_id = question["id"]
        serialized = json.dumps(question, ensure_ascii=False)
        if "chunk_id" in serialized:
            _fail(f"{question_id} contains forbidden chunk_id")
        labels = question.get("labels")
        kind = question.get("question_type")
        if not isinstance(labels, list):
            _fail(f"{question_id} labels must be a list")
        if kind == "refusal":
            if labels or question.get("expected_behavior") != "refuse_insufficient_evidence":
                _fail(f"{question_id} refusal contract is invalid")
            if "2025" not in str(question.get("question", "")) or any(
                entry.effective_date.startswith("2025") for entry in manifest.values()
            ):
                _fail(f"{question_id} refusal is not demonstrably unsupported by the corpus")
            continue
        if not any(label.get("relevance") == 2 for label in labels if isinstance(label, dict)):
            _fail(f"{question_id} answerable question lacks relevance=2")
        if kind == "cross_period":
            periods = set()
        for label in labels:
            if not isinstance(label, dict):
                _fail(f"{question_id} label is not an object")
            version = label.get("document_version_id")
            start, end = label.get("char_start"), label.get("char_end")
            if not isinstance(version, str) or version not in version_to_entry:
                _fail(f"{question_id} label document_version_id does not exist")
            if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end <= start:
                _fail(f"{question_id} invalid char range")
            path, entry = version_to_entry[version]
            if entry.effective_date > str(question.get("as_of")):
                _fail(f"{question_id} label is later than as_of")
            text = texts[path]
            if end > len(text):
                _fail(f"{question_id} char range exceeds extracted text")
            matching_audits = [
                row for row in audits_by_question.get(question_id, [])
                if row.get("document_version_id") == version
                and row.get("char_start") == start
                and row.get("char_end") == end
                and row.get("relevance") == label.get("relevance")
            ]
            if len(matching_audits) != 1:
                _fail(f"{question_id} label must have exactly one matching audit row")
            if matching_audits[0].get("source_excerpt") != text[start:end]:
                _fail(f"{question_id} audit excerpt does not match extracted text")
            if not any(max(start, left) < min(end, right) for left, right in chunks_by_version[version]):
                _fail(f"{question_id} label does not overlap a current chunk")
            span_labels += 1
            resolved_labels += 1
            if kind == "cross_period":
                periods.add(entry.effective_date)
        if kind == "cross_period" and len(periods) < 2:
            _fail(f"{question_id} cross-period question lacks distinct periods")
    if set(audits_by_question) != set(ids):
        _fail("audit question IDs do not exactly match questions")
    return {
        "documents": len(documents),
        "questions": len(questions),
        "dev": splits["dev"],
        "test": splits["test"],
        "chinese": chinese,
        "numeric_or_table": types["numeric"] + types["table"],
        "cross_period": types["cross_period"],
        "refusal": types["refusal"],
        "span_labels": span_labels,
        "resolved_labels": resolved_labels,
        "unresolved_labels": span_labels - resolved_labels,
        "hash_mismatches": 0,
        "active_chunks": len(all_chunks),
        "second_ingest_added": 0,
        "second_ingest_removed": 0,
        "corpus_fingerprint": corpus_fingerprint(raw_manifest),
    }


def document_version_id_for_hash(
    version_to_entry: dict[str, tuple[str, object]], file_sha256: str
) -> str:
    for version, (_, entry) in version_to_entry.items():
        if getattr(entry, "sha256", None) == file_sha256:
            return version
    _fail("chunk refers to a SHA256 absent from corpus manifest")
    raise AssertionError("unreachable")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--corpus", required=True, type=Path)
    parser.add_argument("--questions", required=True, type=Path)
    parser.add_argument("--meta", required=True, type=Path)
    args = parser.parse_args()
    result = validate_assets(
        input_dir=args.input, corpus_path=args.corpus, questions_path=args.questions, meta_path=args.meta
    )
    for key, value in result.items():
        print(f"{key}={value}")


if __name__ == "__main__":
    main()
