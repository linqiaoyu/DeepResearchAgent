"""Verify that the 087 showcase exposes only facts derived from its package."""

from __future__ import annotations

import argparse
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
    values = re.findall(r'data-fact="([^"]+)"', index)
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
    external = len(re.findall(r'(?:href|src)="https?://', index))
    screens = len(re.findall(r'<section data-screen="[^"]+"', index))
    if manifest.get("generated_from") != str(package):
        raise ValueError("site manifest package differs from requested package")
    if not mapping_ids or not set(mapping_ids).issubset(evidence_ids):
        raise ValueError("site mapping references absent package evidence")
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
