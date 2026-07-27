"""Build or verify the offline disclosure corpus from tracked primary PDFs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data/mock_data/disclosure_corpus.json"
PDF = ROOT / "tests/fixtures/cninfo_600519_2026-04-16_annual_report.pdf"


def corpus() -> dict[str, object]:
    text = PdfReader(PDF).pages[5].extract_text()
    if not text:
        raise ValueError(f"no extractable text on page 6: {PDF}")
    return {
        "version": 1,
        "documents": [
            {
                "id": "fixture-primary-moutai-2025",
                "security_code": "600519",
                "keyword": "年度报告",
                "title": "贵州茅台酒股份有限公司2025年年度报告",
                "url": "fixture://cninfo/600519/2025-annual-report",
                "source_type": "disclosure_pdf",
                "source_tier": "primary",
                "published_at": "2026-04-16",
                "credibility": 1.0,
                "source_pdf": PDF.relative_to(ROOT).as_posix(),
                "source_pdf_sha256": hashlib.sha256(PDF.read_bytes()).hexdigest(),
                "page": 6,
                "content": "[[PDF_PAGE=6]]\n" + text,
            }
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
