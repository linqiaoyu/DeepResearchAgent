from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.build_site import (
    _assert_release_safety,
    _assert_showcase_contract,
    _assert_site,
    _home_page,
    _markdown_to_html,
    _rag_page,
    _release_build_log,
    _validate_live_validation,
)


class StaticSiteBuildTests(unittest.TestCase):
    def test_release_scan_rejects_sensitive_artifacts_and_local_build_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dist = Path(tmp)
            (dist / "index.html").write_text("published", encoding="utf-8")
            _assert_release_safety(dist, _release_build_log(1))
            self.assertEqual(_release_build_log(1), "built site/dist\nfiles 1\nvalidation ok\n")

            (dist / "index.html").write_text(
                "Authorization: Bearer forbidden-token", encoding="utf-8"
            )
            with self.assertRaisesRegex(SystemExit, "credential:index.html"):
                _assert_release_safety(dist, _release_build_log(1))
            (dist / "index.html").write_text("published", encoding="utf-8")
            (dist / "manifest.json").write_text(
                "https://cluster.cloud.qdrant.io", encoding="utf-8"
            )
            with self.assertRaisesRegex(SystemExit, "qdrant_endpoint:manifest.json"):
                _assert_release_safety(dist, _release_build_log(2))
            (dist / "manifest.json").write_text("{}", encoding="utf-8")
            (dist / "index.html").write_text("data/corpus/report.pdf", encoding="utf-8")
            with self.assertRaisesRegex(SystemExit, "raw_corpus_reference:index.html"):
                _assert_release_safety(dist, _release_build_log(2))
            (dist / "index.html").write_text("published", encoding="utf-8")
            with self.assertRaisesRegex(SystemExit, "absolute_path:build.log"):
                _assert_release_safety(dist, "built /Users/example/site/dist\n")

    def test_showcase_contract_requires_boundary_and_visual_system(self) -> None:
        home = " ".join(
            (
                "RESEARCH, WITH RECEIPTS",
                "ROUND 087 · FINAL LIVE VALIDATION",
                "NIO 中文",
                "PDD 英文",
                "金融 SUT",
                "浏览精选报告",
                "MEASURABLE, NOT MERELY CLAIMED",
                "RELEASE DISCIPLINE",
            )
        )
        stylesheet = ".hero-home{}.proof-panel{}.metric-section{}.release-section{}"
        _assert_showcase_contract(home, stylesheet)

        with self.assertRaises(SystemExit):
            _assert_showcase_contract(
                home.replace("ROUND 087 · FINAL LIVE VALIDATION", ""), stylesheet
            )

    def test_home_page_exposes_the_reviewed_round_087_facts(self) -> None:
        live = {
            "schema_version": "087-live-validation-v1",
            "scope": "finance_sut_only",
            "corpus": {"documents": 60},
            "topics": 2,
            "provider": "SecCompanyFactsProvider",
            "reports": [
                {"company": "NIO", "language": "中文", "reader_visible_lines": 13, "boilerplate_lines": 0, "answered_metrics": 2, "requested_metrics": 2, "derived_metrics": 1, "workflow_cost_cny": 0.08938328, "rag_cost_cny": 0.036652},
                {"company": "PDD", "language": "英文", "reader_visible_lines": 11, "boilerplate_lines": 0, "answered_metrics": 1, "requested_metrics": 2, "explained_gap": True, "workflow_cost_cny": 0.09856776},
            ],
            "checks": {"structured_manifest": "PASS", "citation_closure": "PASS"},
            "capability_ab": {"comparisons": 8, "promoted": 4, "kept_off": 4},
            "additional_contingency_run": False,
        }
        _validate_live_validation(live)
        page = _home_page({"summary": {}}, {"retrieval_as_of": "2026-07-09"}, live)
        for value in ("NIO 中文报告", "PDD 英文报告", "4/8", "金融 SUT"):
            self.assertIn(value, page)

        live["reports"][0]["reader_visible_lines"] = 12
        with self.assertRaisesRegex(SystemExit, "NIO live-validation facts"):
            _validate_live_validation(live)

    def test_social_share_card_is_project_owned_png(self) -> None:
        card = Path("site/social/og.png")
        self.assertTrue(card.is_file())
        self.assertEqual(card.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

    def test_rag_page_keeps_the_current_default_boundary_and_rerank_limit(self) -> None:
        page = _rag_page()
        self.assertIn("当前默认路径不启用 RAG", page)
        self.assertIn("没有将任何整条流水线提升归因给 rerank", page)

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
