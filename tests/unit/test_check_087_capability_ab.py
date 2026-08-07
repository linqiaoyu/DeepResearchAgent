from __future__ import annotations

import unittest
import subprocess
import sys
from pathlib import Path

from scripts.check_087_capability_ab import _promoted, _single_flag_violation


class CapabilityAbCheckTests(unittest.TestCase):
    def test_cli_reports_missing_results_instead_of_importing_failure(self) -> None:
        root = Path(__file__).resolve().parents[2]
        with self.subTest("direct script execution"):
            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/check_087_capability_ab.py",
                    "--results",
                    "missing-results",
                ],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("capabilities_tested=0", completed.stdout)
        self.assertNotIn("ModuleNotFoundError", completed.stderr)

    def _record(self, *, enabled: bool, answered: int = 2) -> dict[str, object]:
        return {
            "request": {"topic": "NIO 2024", "as_of": "2026-07-01", "depth": 1},
            "manifest": {
                "mode": "llm",
                "retrieval_index_version": "finance-v1",
                "domain": "finance",
                "flags": {"NUMERIC_CHECK_ENABLED": enabled, "RAG_ENABLED": True},
            },
            "shape": {
                "reader_visible_lines": 20,
                "boilerplate_lines": 0,
                "noise_lines": 0,
                "audit_sections_in_report": 0,
                "metrics_requested": 2,
                "metrics_answered": answered,
                "metrics_explained_gap": 2 - answered,
                "derived_metrics_with_provenance": 1,
                "analysis_false_positives": 0,
            },
            "fidelity": {"footnote_misrefs": 0, "magnitude_mismatches": 0},
        }

    def test_promotes_only_a_strict_shape_improvement_without_regression(self) -> None:
        off = self._record(enabled=False, answered=1)
        on = self._record(enabled=True, answered=2)

        self.assertTrue(_promoted(off, on))

        on["shape"]["noise_lines"] = 1  # type: ignore[index]
        self.assertFalse(_promoted(off, on))

    def test_a_longer_report_is_not_a_regression_by_itself(self) -> None:
        """R090: length must not decide capability promotion.

        Under the R087 rule a capability that answered one more metric was
        rejected the moment its report grew a line, which is how every
        analysis-adding capability measured as useless.
        """

        off = self._record(enabled=False, answered=1)
        on = self._record(enabled=True, answered=2)
        on["shape"]["reader_visible_lines"] = 60  # type: ignore[index]

        self.assertTrue(_promoted(off, on))

    def test_rejects_a_pair_that_changes_a_second_flag(self) -> None:
        off = self._record(enabled=False)
        on = self._record(enabled=True)
        on["manifest"]["flags"]["RAG_ENABLED"] = False  # type: ignore[index]

        violation = _single_flag_violation("NUMERIC_CHECK", off, on, "abc", "abc")

        self.assertIn("RAG_ENABLED", violation or "")


if __name__ == "__main__":
    unittest.main()
