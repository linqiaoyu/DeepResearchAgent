from __future__ import annotations

import copy
import unittest

from deepresearch_agent.evaluation.gold_audit import (
    GoldRefillRejected,
    MetricNormalizer,
    audit_slot,
    enforce_refill_gate,
)
from scripts.refill_gold import apply_manifest


def _question() -> dict:
    return {
        "id": "Q01",
        "companies": ["示例公司"],
        "time_anchor": "2024财年",
        "gold": {"must_include": []},
    }


def _normalizer() -> MetricNormalizer:
    return MetricNormalizer(
        {
            "营业收入": "营业收入",
            "营收": "营业收入",
            "归母净利润": "归母净利润",
            "净息差": "净息差",
            "非息收入占比": "非息收入占比",
        }
    )


class GoldAuditTests(unittest.TestCase):
    def test_metric_aliases_are_normalized_before_comparison(self) -> None:
        slot = {
            "fact": "2024营收及同比",
            "value": "示例公司2024年营业收入100亿元，同比增长5%",
            "source_ref": {
                "source_title": "2024年报",
                "extract_text": "2024年营业收入100亿元，同比增长5%",
            },
        }

        row = audit_slot(_question(), slot, 1, _normalizer())

        self.assertEqual(row.metric.status, "PASS")
        self.assertEqual(row.verdict, "PASS")

    def test_metric_mismatch_and_quarter_for_annual_are_defects(self) -> None:
        slot = {
            "fact": "2024净息差",
            "value": "示例公司2024年一季度非息收入占比37%",
            "source_ref": {
                "source_title": "一季报",
                "extract_text": "2024年一季度非息收入占比37%",
            },
        }

        row = audit_slot(_question(), slot, 1, _normalizer())

        self.assertEqual(row.metric.status, "DEFECT")
        self.assertEqual(row.period.status, "DEFECT")
        self.assertEqual(row.verdict, "DEFECT")

    def test_explicit_contract_requires_every_numeric_token_in_excerpt(self) -> None:
        slot = {
            "fact": "2024归母净利润及同比",
            "value": "示例公司2024年归母净利润20亿元，同比增长10%",
            "source_ref": {
                "source_title": "2024年报",
                "extract_text": "2024年归母净利润20亿元",
            },
            "audit_contract": {
                "entities": ["示例公司"],
                "metrics": ["归母净利润"],
                "period": {"kind": "annual", "year": 2024, "label": "2024财年"},
                "dimension": "累计",
                "units": ["亿元", "%"],
                "numeric_tokens": ["20", "10"],
            },
        }

        row = audit_slot(_question(), slot, 1, _normalizer())

        self.assertEqual(row.numeric_excerpt.status, "DEFECT")
        with self.assertRaises(GoldRefillRejected):
            enforce_refill_gate(_question(), slot, 1, _normalizer())

    def test_refill_gate_accepts_a_complete_candidate(self) -> None:
        slot = {
            "fact": "2024归母净利润及同比",
            "value": "示例公司2024年度累计归母净利润20亿元，同比增长10%",
            "source_ref": {
                "source_title": "2024年报",
                "extract_text": "示例公司2024年度累计归母净利润20亿元，同比增长10%",
            },
            "audit_contract": {
                "entities": ["示例公司"],
                "metrics": ["归母净利润"],
                "period": {"kind": "annual", "year": 2024, "label": "2024财年"},
                "dimension": "累计",
                "units": ["亿元", "%"],
                "numeric_tokens": ["20", "10"],
            },
        }

        row = enforce_refill_gate(_question(), slot, 1, _normalizer())

        self.assertEqual(row.verdict, "PASS")

    def test_refill_gate_does_not_mutate_candidate(self) -> None:
        slot = {
            "fact": "2024营收及同比",
            "value": "示例公司2024年度累计营业收入100亿元，同比增长5%",
            "source_ref": {
                "source_title": "2024年报",
                "extract_text": "示例公司2024年度累计营业收入100亿元，同比增长5%",
            },
            "audit_contract": {
                "entities": ["示例公司"],
                "metrics": ["营业收入"],
                "period": {"kind": "annual", "year": 2024, "label": "2024财年"},
                "dimension": "累计",
                "units": ["亿元", "%"],
                "numeric_tokens": ["100", "5"],
            },
        }
        before = copy.deepcopy(slot)

        enforce_refill_gate(_question(), slot, 1, _normalizer())

        self.assertEqual(slot, before)

    def test_refill_manifest_rejects_changes_outside_authorized_slots(self) -> None:
        payload = {
            "meta": {"version": "v1.0"},
            "questions": [_question()],
        }
        manifest = {
            "from_version": "v1.0",
            "authorized_slots": ["Q01s1"],
            "changes": [],
        }

        with self.assertRaisesRegex(ValueError, "exactly match authorized_slots"):
            apply_manifest(payload, manifest, _normalizer())


if __name__ == "__main__":
    unittest.main()
