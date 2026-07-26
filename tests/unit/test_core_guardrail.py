from __future__ import annotations

import unittest

from deepresearch_agent.evaluation.core_guardrail import (
    GUARDRAIL_CASES,
    guardrail_contract_sha256,
    score_guardrail_report,
)


class CoreGuardrailTests(unittest.TestCase):
    def test_contract_digest_is_frozen(self) -> None:
        self.assertEqual(
            guardrail_contract_sha256(),
            "dd0f2ca4ab5a7ec2676f4c45a6e407ea944fb986776db7e43e109be253d2dbc8",
        )

    def test_hengrui_known_transcription_error_fails(self) -> None:
        report = """# topic

## 关键发现
- 2025年营业收入为316.2941619383亿元，较2024年的279.8460534206亿元增长13.02%。 [^1]
- 2025年归母净利润为7,711,054,811.98元，较2024年的6,336,527,14.75元增长21.69%。 [^2]
- 2025年主营业务毛利率为85.06%，较2024年增加0.01个百分点。 [^3]

## 参考来源
"""
        result = score_guardrail_report(report, GUARDRAIL_CASES[1])
        self.assertEqual(result["correct_metrics"], 2)
        self.assertEqual(result["hallucinated_number_count"], 1)
        self.assertFalse(result["passed"])

    def test_equivalent_units_and_rounding_pass(self) -> None:
        report = """# topic

## 关键发现
- 2025年营业收入为1688.38亿元，较2024年的1708.99亿元下降1.21%。 [^1]
- 2025年归母净利润为823.20亿元，较2024年的862.28亿元下降4.53%。 [^2]
- 2025年主营业务毛利率为91.23%，较2024年下降0.78个百分点。 [^3]

## 参考来源
"""
        result = score_guardrail_report(report, GUARDRAIL_CASES[0])
        self.assertEqual(result["correct_metrics"], 3)
        self.assertEqual(result["hallucinated_number_count"], 0)
        self.assertTrue(result["passed"])


if __name__ == "__main__":
    unittest.main()
