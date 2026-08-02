"""Offline fidelity metrics for a research package produced in round 082."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


_NUMBER = re.compile(r"(?<![\d.])[+-]?\d[\d,]*(?:\.\d+)?(?![\d.])")


@dataclass(frozen=True)
class FidelityMetrics:
    sampled_numbers: int
    footnote_misrefs: int
    magnitude_mismatches: int
    missing_source_dates: int


def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _numeric_record(item: dict[str, Any]) -> tuple[Decimal, str] | None:
    """Return the exported structured value/unit pair when both are present."""
    record = item.get("structured_record", item)
    if not isinstance(record, dict):
        return None
    value, unit = record.get("value"), record.get("unit")
    if value is None or not isinstance(unit, str) or not unit:
        return None
    try:
        return Decimal(str(value)), unit
    except InvalidOperation:
        return None


def _integer_digits(value: Decimal) -> int:
    return len(str(abs(value).to_integral_value()))


def _has_matching_magnitude(*, value: Decimal, unit: str, report: str) -> bool:
    expected_digits = _integer_digits(value)
    for candidate in _NUMBER.findall(report):
        normalized = candidate.replace(",", "")
        try:
            parsed = Decimal(normalized)
        except InvalidOperation:
            continue
        if _integer_digits(parsed) == expected_digits and unit in report[
            report.find(candidate) + len(candidate) : report.find(candidate) + len(candidate) + len(unit) + 3
        ]:
            return True
    return False


def measure(package: Path) -> FidelityMetrics:
    """Measure one package without contacting providers or the network."""
    evidence = _load_json(package / "audit_bundle" / "evidence.json")
    report_payload = _load_json(package / "audit_bundle" / "report.json")
    report = (package / "report.md").read_text(encoding="utf-8")
    if not isinstance(evidence, list) or not isinstance(report_payload, dict):
        raise ValueError("audit bundle has an invalid JSON shape")
    claims = report_payload.get("claims", [])
    if not isinstance(claims, list):
        raise ValueError("audit bundle report claims must be a list")
    cited_ids = {
        evidence_id
        for claim in claims
        if isinstance(claim, dict)
        for evidence_id in claim.get("evidence_ids", [])
        if isinstance(evidence_id, str) and not evidence_id.startswith("footnote:")
    }
    footnote_misrefs = sum(
        1
        for claim in claims
        if isinstance(claim, dict)
        for evidence_id in claim.get("evidence_ids", [])
        if isinstance(evidence_id, str) and evidence_id.startswith("footnote:")
    )
    sampled: list[tuple[Decimal, str]] = []
    missing_source_dates = 0
    for item in evidence:
        if not isinstance(item, dict):
            continue
        source_date = item.get("source_pub_date")
        if source_date in (None, "", "unknown", "Unknown", "未知"):
            missing_source_dates += 1
        numeric = _numeric_record(item)
        if numeric is not None and item.get("evidence_id") in cited_ids:
            sampled.append(numeric)
    magnitude_mismatches = sum(
        not _has_matching_magnitude(value=value, unit=unit, report=report)
        for value, unit in sampled
    )
    return FidelityMetrics(
        sampled_numbers=len(sampled),
        footnote_misrefs=footnote_misrefs,
        magnitude_mismatches=magnitude_mismatches,
        missing_source_dates=missing_source_dates,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, required=True)
    args = parser.parse_args()
    metrics = measure(args.package)
    print(f"sampled_numbers={metrics.sampled_numbers}")
    print(f"footnote_misrefs={metrics.footnote_misrefs}")
    print(f"magnitude_mismatches={metrics.magnitude_mismatches}")
    print(f"missing_source_dates={metrics.missing_source_dates}")
    return 0 if metrics.footnote_misrefs == metrics.magnitude_mismatches == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
