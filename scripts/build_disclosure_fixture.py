"""Build or verify the offline disclosure corpus from tracked primary PDFs."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

import pdfplumber
from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data/mock_data/disclosure_corpus.json"
MOUTAI_PDF = ROOT / "tests/fixtures/cninfo_600519_2026-04-16_annual_report.pdf"
CATL_PDF = ROOT / "tests/fixtures/catl_2022_070_excerpt.pdf"


def _layout_index(
    pdf_path: Path,
    page_number: int,
) -> tuple[list[dict[str, object]], list[list[list[str | None]]]]:
    with pdfplumber.open(pdf_path) as document:
        page = document.pages[page_number - 1]
        words = page.extract_words()
        tables = page.extract_tables()
    return [
        {
            "text": str(word["text"]),
            "bbox": {
                "page": page_number,
                "x0": round(float(word["x0"]), 3),
                "top": round(float(word["top"]), 3),
                "x1": round(float(word["x1"]), 3),
                "bottom": round(float(word["bottom"]), 3),
            },
        }
        for word in words
        if re.search(r"\d", str(word["text"]))
    ], tables


def _document(
    *,
    identifier: str,
    security_code: str,
    keyword: str,
    title: str,
    url: str,
    published_at: str,
    pdf_path: Path,
    page_number: int,
) -> dict[str, object]:
    text = PdfReader(pdf_path).pages[page_number - 1].extract_text()
    if not text:
        raise ValueError(f"no extractable text on page {page_number}: {pdf_path}")
    bbox_index, table_index = _layout_index(pdf_path, page_number)
    return {
        "id": identifier,
        "security_code": security_code,
        "keyword": keyword,
        "title": title,
        "url": url,
        "source_type": "disclosure_pdf",
        "source_tier": "primary",
        "published_at": published_at,
        "credibility": 1.0,
        "source_pdf": pdf_path.relative_to(ROOT).as_posix(),
        "source_pdf_sha256": hashlib.sha256(pdf_path.read_bytes()).hexdigest(),
        "page": page_number,
        "bbox_index": bbox_index,
        "table_index": table_index,
        "content": f"[[PDF_PAGE={page_number}]]\n" + text,
    }


def corpus() -> dict[str, object]:
    return {
        "version": 1,
        "documents": [
            _document(
                identifier="fixture-primary-moutai-2025",
                security_code="600519",
                keyword="年度报告",
                title="贵州茅台酒股份有限公司2025年年度报告",
                url="fixture://cninfo/600519/2025-annual-report",
                published_at="2026-04-16",
                pdf_path=MOUTAI_PDF,
                page_number=6,
            ),
            *[
                _document(
                    identifier=f"fixture-primary-catl-hungary-{page_number}",
                    security_code="300750",
                    keyword="匈牙利",
                    title="宁德时代关于投资建设匈牙利时代新能源电池产业基地项目的公告",
                    url=f"fixture://cninfo/300750/2022-hungary-project/page-{page_number}",
                    published_at="2022-08-13",
                    pdf_path=CATL_PDF,
                    page_number=page_number,
                )
                for page_number in (1, 2)
            ],
        ],
    }


def rendered() -> str:
    return json.dumps(corpus(), ensure_ascii=False, indent=2) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = rendered()
    if args.check:
        if OUTPUT.read_text(encoding="utf-8") != expected:
            raise SystemExit("disclosure fixture differs; run build_disclosure_fixture.py")
        print(f"fixture_sha256={hashlib.sha256(expected.encode()).hexdigest()}")
        return
    OUTPUT.write_text(expected, encoding="utf-8")
    print(f"wrote={OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
