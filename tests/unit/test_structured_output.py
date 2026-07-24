from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from openpyxl import load_workbook
from pydantic import ValidationError

from deepresearch_agent.schemas import (
    CriticReport,
    Evidence,
    Issue,
    MetricRow,
    NumericFields,
    ResearchState,
)
from deepresearch_agent.structured_output import (
    build_structured_output,
    render_structured_json,
    render_structured_markdown,
    write_structured_table,
)


def evidence(
    item_id: str,
    *,
    metric: str = "营收",
    scope: str = "累计",
    value: float = 100.0,
) -> Evidence:
    claim = f"宁德时代 2024 {scope}{metric}为 {value} 亿元"
    return Evidence(
        id=item_id,
        research_id="structured-run",
        sub_question_id="q1",
        claim=claim,
        claim_type="data",
        source_url=f"https://example.com/{item_id}",
        source_title=item_id,
        source_pub_date=date(2026, 4, 20),
        extract_text=claim,
        confidence=0.9,
        numeric_fields=NumericFields(
            entity="宁德时代",
            metric_name=metric,
            period="2024",
            dimension=scope,
            value=value,
            unit="亿元",
        ),
    )


class StructuredOutputTests(unittest.TestCase):
    def test_schema_requires_unverified_status_without_evidence(self) -> None:
        kwargs = {
            "entity": "宁德时代",
            "metric": "营收",
            "normalized_metric": "营业收入",
            "period": "2024",
            "scope": "累计",
            "value": 100.0,
            "unit": "亿元",
            "confidence": 0.5,
            "evidence_ids": [],
        }
        with self.assertRaises(ValidationError):
            MetricRow(**kwargs)
        row = MetricRow(**kwargs, verification_status="unverified")
        self.assertEqual(row.verification_status, "unverified")

    def test_scope_conflict_is_explicit_and_normalization_is_reused(self) -> None:
        output = build_structured_output(
            ResearchState(
                topic="宁德时代对比",
                evidence_store=[
                    evidence("annual", scope="累计"),
                    evidence("quarter", scope="单季", value=30.0),
                ],
            )
        )
        table = output.comparison_table
        self.assertEqual(
            {row.normalized_metric for row in table.rows},
            {"营业收入"},
        )
        self.assertFalse(table.scope_consistent)
        self.assertIn("单季, 累计", table.scope_notes[0])

    def test_same_scope_has_no_conflict(self) -> None:
        table = build_structured_output(
            ResearchState(
                topic="宁德时代对比",
                evidence_store=[evidence("a"), evidence("b", value=120.0)],
            )
        ).comparison_table
        self.assertTrue(table.scope_consistent)
        self.assertEqual(table.scope_notes, [])

    def test_risk_without_matching_evidence_is_marked_unverified(self) -> None:
        output = build_structured_output(
            ResearchState(
                topic="风险",
                evidence_store=[evidence("a")],
                critic_report=CriticReport(
                    passed=False,
                    overall_quality=0.5,
                    issues=[
                        Issue(
                            issue_type="missing_counterargument",
                            severity="high",
                            affected_claims=["not in evidence"],
                            message="缺少反方证据",
                        )
                    ],
                ),
            )
        )
        risk = output.risk_matrix.risks[0]
        self.assertEqual(risk.evidence_ids, [])
        self.assertEqual(risk.verification_status, "unverified")

    def test_markdown_json_and_excel_rendering_are_deterministic(self) -> None:
        output = build_structured_output(
            ResearchState(topic="宁德时代对比", evidence_store=[evidence("a")])
        )
        self.assertEqual(
            render_structured_markdown(output),
            render_structured_markdown(output),
        )
        self.assertEqual(render_structured_json(output), render_structured_json(output))
        with tempfile.TemporaryDirectory() as tmp:
            first = write_structured_table(output, Path(tmp) / "first")
            second = write_structured_table(output, Path(tmp) / "second")
            self.assertEqual(first.read_bytes(), second.read_bytes())
            workbook = load_workbook(first, read_only=True)
            self.assertEqual(workbook["metrics"]["C2"].value, "营业收入")
            workbook.close()

    def test_table_export_falls_back_to_deterministic_csv(self) -> None:
        output = build_structured_output(
            ResearchState(topic="宁德时代对比", evidence_store=[evidence("a")])
        )
        with tempfile.TemporaryDirectory() as tmp:
            with patch(
                "deepresearch_agent.structured_output.importlib.util.find_spec",
                return_value=None,
            ):
                first = write_structured_table(output, Path(tmp) / "first")
                second = write_structured_table(output, Path(tmp) / "second")
            self.assertEqual(first.suffix, ".csv")
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertIn("normalized_metric", first.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
