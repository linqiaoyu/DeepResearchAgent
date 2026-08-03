from __future__ import annotations

import unittest
import json
import sqlite3
import tempfile
from pathlib import Path

from scripts.check_087_site_facts import check


class SiteFactsTests(unittest.TestCase):
    def test_final_showcase_matches_its_nio_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "package"
            dist = root / "dist"
            (package / "audit_bundle").mkdir(parents=True)
            (package / "runtime").mkdir()
            dist.mkdir()
            (package / "audit_bundle" / "evidence.json").write_text(
                json.dumps([{"evidence_id": "e-1"}]), encoding="utf-8"
            )
            (dist / "manifest.json").write_text(
                json.dumps(
                    {
                        "generated_from": str(package),
                        "facts": {
                            "display_numbers": ["12"],
                            "workflow_cost": "0.1",
                            "rag_cost": "0.2",
                            "elapsed_seconds": "3",
                            "evidence_total": "4",
                            "cited_sources": "5",
                        },
                    }
                ),
                encoding="utf-8",
            )
            with sqlite3.connect(package / "runtime" / "research.db") as conn:
                conn.execute("CREATE TABLE evidence (id TEXT PRIMARY KEY)")
                conn.execute("INSERT INTO evidence VALUES ('source-1')")
            (dist / "index.html").write_text(
                "".join(
                    f'<section data-screen="{index}"></section>'
                    for index in range(5)
                )
                + "".join(
                    f'<article data-capability="FLAG_{index}"></article>'
                    for index in range(25)
                )
                + '<span data-fact="12" data-evidence-id="e-1">12</span>'
                + '<blockquote data-source-evidence-id="source-1"></blockquote>',
                encoding="utf-8",
            )
            values = check(dist, package)

        self.assertEqual(values["unmatched_numbers"], 0)
        self.assertEqual(values["external_requests"], 0)
        self.assertEqual(values["noscript_readable_sections"], 5)


if __name__ == "__main__":
    unittest.main()
