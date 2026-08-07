from __future__ import annotations

import unittest

from scripts.check_087_report_shape import measure


class ReportShapeTests(unittest.TestCase):
    def test_x20f_filing_and_legal_template_are_reader_false_positives(self) -> None:
        report = """# Report

## 风险与限制
- outdated_source (medium): Source 'nio-20241231x20f.htm' is old.

## 未验证假设
- You should read this annual report; actual future results may be materially different.

## 参考来源
[^1]: source
"""

        values = measure(report)

        self.assertEqual(values["analysis_false_positives"], 2)
        self.assertGreaterEqual(values["noise_lines"], 2)

    def test_a_long_analytical_report_carries_no_noise(self) -> None:
        """R090: substance must not read as a shape defect.

        `reader_visible_lines <= 40` used to reject this report, so the gate
        preferred a two-line metric dump over an explained one.
        """

        body = "\n".join(f"- 第 {index} 条分析结论，来源见脚注。 [^1]" for index in range(60))
        report = f"# Report\n\n## 详细分析\n{body}\n\n## 参考来源\n[^1]: source\n"

        values = measure(report)

        self.assertGreater(values["reader_visible_lines"], 40)
        self.assertEqual(values["noise_lines"], 0)


if __name__ == "__main__":
    unittest.main()
