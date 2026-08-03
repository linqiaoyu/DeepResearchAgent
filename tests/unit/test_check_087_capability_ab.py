from __future__ import annotations

import unittest

from scripts.check_087_capability_ab import _promoted, _single_flag_violation


class CapabilityAbCheckTests(unittest.TestCase):
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

        on["shape"]["reader_visible_lines"] = 21  # type: ignore[index]
        self.assertFalse(_promoted(off, on))

    def test_rejects_a_pair_that_changes_a_second_flag(self) -> None:
        off = self._record(enabled=False)
        on = self._record(enabled=True)
        on["manifest"]["flags"]["RAG_ENABLED"] = False  # type: ignore[index]

        violation = _single_flag_violation("NUMERIC_CHECK", off, on, "abc", "abc")

        self.assertIn("RAG_ENABLED", violation or "")


if __name__ == "__main__":
    unittest.main()
