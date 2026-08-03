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


if __name__ == "__main__":
    unittest.main()
