"""Measure extraction and layout coverage for explicitly supplied public PDFs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pdfplumber
from pypdf import PdfReader


def probe(paths: list[Path]) -> dict[str, object]:
    documents: list[dict[str, object]] = []
    for path in paths:
        pypdf_text = "".join(page.extract_text() or "" for page in PdfReader(path).pages)
        with pdfplumber.open(path) as pdf:
            words = [word for page in pdf.pages for word in page.extract_words()]
            plumber_text = " ".join(str(word.get("text") or "") for word in words).strip()
        documents.append({"name": path.name, "pypdf_chars": len(pypdf_text), "pdfplumber_chars": len(plumber_text), "bbox_words": len(words), "bbox_available": bool(words)})
    if not documents:
        raise ValueError("at least one explicit public PDF probe is required")
    return {"documents": documents, "document_count": len(documents), "bbox_available_rate": sum(bool(item["bbox_available"]) for item in documents) / len(documents)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = probe(args.pdf)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
