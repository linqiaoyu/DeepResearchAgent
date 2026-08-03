from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from deepresearch_agent.provenance import FLAG_CLASSIFICATIONS, settings_flag_snapshot
from deepresearch_agent.settings import Settings
from scripts.check_087_readme_facts import HEADINGS, _architecture_count_matches, check


class ReadmeFactsTests(unittest.TestCase):
    def test_architecture_count_is_checked_against_the_current_graph(self) -> None:
        self.assertTrue(_architecture_count_matches("当前工作流的 15 个节点"))
        self.assertFalse(_architecture_count_matches("当前工作流的 14 个节点"))

    def test_checker_accepts_a_complete_generated_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "package"
            package.mkdir()
            report = "# final\n\n## 参考来源\nsource"
            (package / "report.md").write_text(report, encoding="utf-8")
            flags = settings_flag_snapshot(
                Settings(storage_path=Path("research.db")),
                include_disabled_experimental=True,
            )
            rows = "\n".join(
                f"| {flag} | {'on' if value else 'off'} | recorded | decision |"
                for flag, value in sorted(flags.items())
            )
            readme = root / "README.md"
            readme.write_text(
                "\n".join(HEADINGS)
                + "\n<!-- BEGIN 087 EMBEDDED REPORT -->\n"
                + report
                + "\n<!-- END 087 EMBEDDED REPORT -->\n"
                + rows,
                encoding="utf-8",
            )
            with patch(
                "scripts.check_087_readme_facts._unverifiable_claims",
                return_value=0,
            ):
                values = check(readme, package)

        self.assertEqual(values["capability_rows"], len(FLAG_CLASSIFICATIONS))
        self.assertEqual(values["flag_state_mismatches"], 0)
        self.assertEqual(values["embedded_report_matches_artifact"], 1)
        self.assertEqual(values["unverifiable_claims"], 0)
