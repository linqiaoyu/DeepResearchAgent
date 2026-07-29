from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.build_site import _assert_showcase_contract, _assert_site, _markdown_to_html


class StaticSiteBuildTests(unittest.TestCase):
    def test_showcase_contract_requires_boundary_and_visual_system(self) -> None:
        home = " ".join(
            (
                "RESEARCH, WITH RECEIPTS",
                "无实时 LLM、搜索或付费调用",
                "浏览精选报告",
                "MEASURABLE, NOT MERELY CLAIMED",
                "RELEASE DISCIPLINE",
            )
        )
        stylesheet = ".hero-home{}.proof-panel{}.metric-section{}.release-section{}"
        _assert_showcase_contract(home, stylesheet)

        with self.assertRaises(SystemExit):
            _assert_showcase_contract(
                home.replace("无实时 LLM、搜索或付费调用", ""), stylesheet
            )

    def test_social_share_card_is_project_owned_png(self) -> None:
        card = Path("site/social/og.png")
        self.assertTrue(card.is_file())
        self.assertEqual(card.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

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
            (Path(tmp) / "methodology.html").write_text(
                "0.6134 + 0.1865 - 0.0585 = 0.7414", encoding="utf-8"
            )
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

    def test_historical_judge_decomposition_is_limited_to_methodology(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            reports = Path(tmp) / "reports"
            reports.mkdir()
            (Path(tmp) / "methodology.html").write_text(
                "0.6134 + 0.1865 - 0.0585 = 0.7414", encoding="utf-8"
            )
            (reports / "Q01.html").write_text(
                "<h2>参考来源</h2>" + "".join(f'<li id="ref-{index}">x</li>' for index in range(1, 8)),
                encoding="utf-8",
            )
            _assert_site(Path(tmp))

            (reports / "Q01.html").write_text(
                (reports / "Q01.html").read_text(encoding="utf-8") + "0.7414",
                encoding="utf-8",
            )
            with self.assertRaises(SystemExit):
                _assert_site(Path(tmp))
