from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.check_domain_boundary import _concrete_domain_import_sites
from scripts.round.check_plan_ledger import validate as validate_plan_ledger


ROOT = Path(__file__).resolve().parents[2]


class DomainBoundaryTests(unittest.TestCase):
    def test_literal_ratchet_matches_versioned_allowlist(self) -> None:
        completed = subprocess.run(
            [sys.executable, "scripts/check_domain_boundary.py"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
            stdin=subprocess.DEVNULL,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("import_sites=0 literal_files=3 literal_hits=9", completed.stdout)

    def test_import_site_count_is_measured_from_source(self) -> None:
        self.assertEqual(_concrete_domain_import_sites(), 0)

    def test_core_has_no_hard_coded_finance_pack_load(self) -> None:
        offenders = [
            path.relative_to(ROOT).as_posix()
            for path in (ROOT / "src/deepresearch_agent").rglob("*.py")
            if 'load_domain_pack("finance")' in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(offenders, [])

    def test_residual_documentation_matches_allowlist(self) -> None:
        allowlist = json.loads(
            (ROOT / "data/domain_boundary/allowlist.json").read_text(
                encoding="utf-8"
            )
        )
        residuals = (
            ROOT / "docs/decisions/043/domain-boundary-residual.md"
        ).read_text(encoding="utf-8")
        self.assertTrue(allowlist)
        for path in allowlist:
            row = next(
                line for line in residuals.splitlines() if f"`{path}`" in line
            )
            columns = [column.strip() for column in row.split("|")]
            self.assertGreaterEqual(len(columns), 6)
            self.assertTrue(columns[-2])
        self.assertEqual(residuals.count("| 移除条件 |"), 1)

    def test_criteria_commands_are_explicit_argument_vectors(self) -> None:
        criteria = json.loads((ROOT / "docs/decisions/043/043_criteria.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(criteria), 4)
        self.assertTrue(all(isinstance(item["command"], list) for item in criteria))

    def test_progress_ledger_declares_the_whole_round(self) -> None:
        blocks = json.loads((ROOT / "docs/decisions/043/043_blocks.json").read_text(encoding="utf-8"))
        self.assertEqual(blocks, [f"B{index}" for index in range(9)])

    def test_044_plan_ledger_has_one_justified_terminal_entry_per_plan_ref(self) -> None:
        validate_plan_ledger(
            ROOT / "docs/decisions/044/044_plan.json",
            ROOT / "docs/decisions/044/044_plan_ledger.json",
        )

    def test_plan_ledger_rejects_duplicate_and_unjustified_deferred_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = root / "plan.json"
            ledger = root / "ledger.json"
            plan.write_text('[{"plan_ref":"one"}]', encoding="utf-8")
            ledger.write_text(
                '[{"plan_ref":"one","status":"DEFERRED"},'
                '{"plan_ref":"one","status":"PASS"}]',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "exactly one"):
                validate_plan_ledger(plan, ledger)
