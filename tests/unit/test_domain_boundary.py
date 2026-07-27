from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from scripts.check_domain_boundary import _concrete_domain_import_sites


ROOT = Path(__file__).resolve().parents[2]


class DomainBoundaryTests(unittest.TestCase):
    def test_literal_ratchet_matches_versioned_allowlist(self) -> None:
        completed = subprocess.run(
            [sys.executable, "scripts/check_domain_boundary.py"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("import_sites=0 literal_files=19 literal_hits=112", completed.stdout)

    def test_import_site_count_is_measured_from_source(self) -> None:
        self.assertEqual(_concrete_domain_import_sites(), 0)

    def test_criteria_commands_are_explicit_argument_vectors(self) -> None:
        criteria = json.loads((ROOT / "data/round/043_criteria.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(criteria), 4)
        self.assertTrue(all(isinstance(item["command"], list) for item in criteria))

    def test_progress_ledger_declares_the_whole_round(self) -> None:
        blocks = json.loads((ROOT / "data/round/043_blocks.json").read_text(encoding="utf-8"))
        self.assertEqual(blocks, [f"B{index}" for index in range(9)])
