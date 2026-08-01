from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.build_site import (
    _assert_release_safety,
    _assert_showcase_contract,
    _assert_site,
    _markdown_to_html,
    _rag_page,
    _release_build_log,
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

    def test_rag_page_keeps_the_negative_quality_result_and_rerank_limit(self) -> None:
        page = _rag_page(
            {
                "corpus": {"version": "finance_v1", "documents": 60, "chunks": 22953, "fingerprint": "f" * 64},
                "index": {"version": "idx-v1", "rebuild_seconds": 1.0, "cost_cny": 0.1},
                "retrieval": {"bm25": {"recall_at_20": 0.0, "ndcg_at_10": 0.0}, "hybrid_rerank": {"recall_at_20": 0.1, "ndcg_at_10": 0.0}, "quality_gate": "FAIL", "decision": "No retuning."},
                "trace": {"kind": "real probe", "lexical_candidates": 50, "dense_candidates": 50, "delivered_candidates": 8, "rerank_status": "ok", "cost_cny": 0.1},
                "limitations": ["rerank 默认开启，其单项检索收益在本轮未经测量；展示的提升数字来自整条流水线，不可归因到 rerank。"],
            }
        )
        self.assertIn("质量门槛：<strong>FAIL</strong>", page)
        self.assertIn("不可归因到 rerank", page)

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
