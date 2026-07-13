from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.build_site import _assert_site, _markdown_to_html


class StaticSiteBuildTests(unittest.TestCase):
    def test_references_are_deduplicated_and_citations_are_remapped(self) -> None:
        rendered = _markdown_to_html(
            """# Report
数据截至：1970-01-01
正文。[^2][^1]

## 参考来源
[^1]: First. https://example.com/a (1970-01-01)
[^2]: Duplicate. https://example.com/a (1970-01-01)
[^3]: Second. https://example.com/b (2026-07-09)
"""
        )

        self.assertEqual(rendered.count("<h2>参考来源</h2>"), 1)
        self.assertEqual(rendered.count('<li id="ref-'), 2)
        self.assertNotIn("1970-01-01", rendered)
        self.assertIn('href="#ref-1"', rendered)

    def test_negative_assertion_rejects_legacy_site_number(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            reports = Path(tmp) / "reports"
            reports.mkdir()
            (reports / "Q01.html").write_text(
                "<h2>参考来源</h2>" + "".join(f'<li id="ref-{index}">x</li>' for index in range(1, 8)),
                encoding="utf-8",
            )
            with self.assertRaises(SystemExit):
                (reports / "Q01.html").write_text(
                    (reports / "Q01.html").read_text(encoding="utf-8") + "0.7803",
                    encoding="utf-8",
                )
                _assert_site(Path(tmp))
