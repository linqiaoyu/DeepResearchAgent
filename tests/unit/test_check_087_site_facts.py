from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.build_site import _write_css
from scripts.check_087_site_facts import check


class SiteFactsTests(unittest.TestCase):
    def test_checker_rejects_a_missing_reader_visible_live_fact(self) -> None:
        facts_path = Path("data/demo/live_validation_087.json")
        facts = json.loads(facts_path.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            dist = Path(tmp)
            (dist / "assets").mkdir()
            _write_css(dist / "assets" / "styles.css")
            (dist / "manifest.json").write_text(
                json.dumps(
                    {
                        "generated_from": {"live_validation": str(facts_path)},
                        "live_validation": facts,
                    }
                ),
                encoding="utf-8",
            )
            (dist / "index.html").write_text(
                "ROUND 087 · FINAL LIVE VALIDATION NIO 中文报告 PDD 英文报告 "
                "13 11 SecCompanyFactsProvider 金融 SUT",
                encoding="utf-8",
            )
            (dist / "methodology.html").write_text(
                "Round 087 最终 live 验证 SecCompanyFactsProvider 60 finance SUT",
                encoding="utf-8",
            )
            values = check(dist, facts_path)
            self.assertEqual(values["stylesheet_matches_cfca7fb"], 1)

            (dist / "index.html").write_text("NIO 中文报告", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "site home misses"):
                check(dist, facts_path)


if __name__ == "__main__":
    unittest.main()
