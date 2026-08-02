"""Acceptance probe for task 081 block A numeric rendering fidelity."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from deepresearch_agent.agents.reporter import ReporterAgent
from deepresearch_agent.domains.finance import FinanceGroundedFactRenderer
from deepresearch_agent.schemas import Evidence, StructuredDataRecord

UNITS = ("元", "CNY", "USD", "%", "万元", "亿元", "千元", "百万元")
VALUES = (
    "71332000000", "362012554000", "1200", "100", "30", "10.50", "2050000", "1000",
)


def _trimmed(value: Decimal) -> str:
    rendered = format(value, "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


def _evidence(value: Decimal, unit: str) -> Evidence:
    record = StructuredDataRecord(
        entity="acceptance", symbol="ACC", metric_name="metric", period="2024",
        dimension="annual", value=value, unit=unit, data_source="fixture",
        as_of=date(2026, 8, 2), source_pub_date=date(2024, 1, 1),
    )
    return Evidence(
        research_id="081", sub_question_id="A", claim="fixture", claim_type="data",
        source_url="fixture://081", source_title="fixture", source_pub_date=date(2024, 1, 1),
        extract_text="fixture", structured_record=record,
    )


def main() -> int:
    reporter = ReporterAgent()
    facts = FinanceGroundedFactRenderer()
    mismatches = 0
    for raw in VALUES:
        value = Decimal(raw)
        for unit in UNITS:
            expected_reporter = f"{_trimmed(value)}{unit}"
            expected_facts = (
                f"{value:,f}元" if unit == "元" else expected_reporter
            )
            actual_reporter = reporter._typed_evidence_claim(_evidence(value, unit))
            actual_facts = facts._format_value(value, unit)
            if expected_reporter not in actual_reporter or actual_facts != expected_facts:
                mismatches += 1
    print(f"render_mismatches={mismatches}")
    return 0 if mismatches == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
