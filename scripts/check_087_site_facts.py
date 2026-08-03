"""Verify that the 087 showcase exposes only facts derived from its package."""

from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path


def _normal(value: str) -> str:
    value = value.replace(",", "")
    return value.rstrip("0").rstrip(".") if "." in value else value


def check(dist: Path, package: Path) -> dict[str, int]:
    index = (dist / "index.html").read_text(encoding="utf-8")
    manifest = json.loads((dist / "manifest.json").read_text(encoding="utf-8"))
    facts = manifest.get("facts", {})
    visible = html.unescape(re.sub(r"<[^>]+>", " ", index))
    values = re.findall(r"(?<![\w,])\d[\d,]*(?:\.\d+)?%?", visible)
    expected = {
        _normal(str(value))
        for value in facts.get("display_numbers", [])
        + [
            facts.get("workflow_cost", ""),
            facts.get("rag_cost", ""),
            facts.get("elapsed_seconds", ""),
            facts.get("evidence_total", ""),
            facts.get("cited_sources", ""),
        ]
    }
    matched = sum(_normal(value) in expected for value in values)
    evidence = json.loads((package / "audit_bundle" / "evidence.json").read_text(encoding="utf-8"))
    evidence_ids = {str(item.get("evidence_id")) for item in evidence}
    mapping_ids = re.findall(r'data-evidence-id="([^"]+)"', index)
    source_mappings = re.findall(r'data-source-evidence-id="([^"]+)"', index)
    capabilities = re.findall(r'data-capability="([^"]+)"', index)
    external = len(re.findall(r'(?:href|src)="https?://', index))
    screens = len(re.findall(r'<section data-screen="[^"]+"', index))
    if manifest.get("generated_from") != str(package):
        raise ValueError("site manifest package differs from requested package")
    if not mapping_ids or not set(mapping_ids).issubset(evidence_ids):
        raise ValueError("site mapping references absent package evidence")
    if len(capabilities) != 25 or len(set(capabilities)) != 25:
        raise ValueError("site capability matrix is incomplete")
    if len(source_mappings) != 1:
        raise ValueError("site source highlight mapping is missing")
    source_db = package / "runtime" / "research.db"
    source_query = "SELECT 1 FROM evidence WHERE id = ?"
    if facts.get("source_origin") == "registered_corpus":
        source_db = Path("data/runtime/085-assets.db")
        source_query = "SELECT 1 FROM chunk WHERE id = ?"
    with __import__("sqlite3").connect(source_db) as conn:
        present = conn.execute(source_query, (source_mappings[0],)).fetchone()
    if present is None:
        raise ValueError("site source highlight references absent runtime evidence")
    return {
        "site_numbers": len(values),
        "numbers_matched_to_package": matched,
        "unmatched_numbers": len(values) - matched,
        "external_requests": external,
        "noscript_readable_sections": screens,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist", type=Path, required=True)
    parser.add_argument("--package", type=Path, required=True)
    args = parser.parse_args()
    try:
        values = check(args.dist, args.package)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"site_check_error={exc}")
        raise SystemExit(1) from exc
    for key, value in values.items():
        print(f"{key}={value}")
    valid = (
        values["unmatched_numbers"] == 0
        and values["external_requests"] == 0
        and values["noscript_readable_sections"] == 5
    )
    raise SystemExit(0 if valid else 1)


if __name__ == "__main__":
    main()
