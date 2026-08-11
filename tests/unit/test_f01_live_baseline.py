from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from check_f01_live_baseline import build_proof, evaluate  # noqa: E402


def _result(number: int) -> dict[str, object]:
    return {
        "id": f"Q{number:02d}",
        "status": "done",
        "provider_fidelity": {
            "llm": "live",
            "retrieval": "live",
            "structured_data": "live",
        },
        "evidence_count": 2,
        "false_premise_failed": False,
        "cost_cny": 0.1,
        "judge_cost_cny": 0.01,
        "latency_seconds": 1.0,
        "mechanical": {
            "evidence_reachable_by_reader": 1,
            "orphaned_sub_questions": 0,
            "evidence_funnel": {
                "retrieved_sources": 2,
                "extracted_evidence": 2,
                "packed_evidence": 2,
                "cited_evidence": 1,
                "reader_visible_evidence": 1,
            },
        },
    }


class F01LiveBaselineTests(unittest.TestCase):
    def _build(self, results: list[dict[str, object]]) -> dict[str, object]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "merged.json"
            path.write_text(
                json.dumps({"results": results, "superseded_failures": []}),
                encoding="utf-8",
            )
            ledgers = []
            for number in range(1, 7):
                ledger = root / f"shard{number}.jsonl"
                ledger.write_text(json.dumps({"cost_cny": 0.55}) + "\n", encoding="utf-8")
                ledgers.append(ledger)
            return build_proof(path, ledger_paths=ledgers)

    def _diagnostic_results(self) -> list[dict[str, object]]:
        results = [_result(number) for number in range(1, 31)]
        results[12] = {
            **results[12],
            "status": "error",
            "error_type": "LLMRetryExhaustedError",
            "provider_fidelity": {
                "llm": "absent",
                "retrieval": "absent",
                "structured_data": "absent",
            },
            "evidence_count": 0,
            "cost_cny": 0,
            "judge_cost_cny": 0,
            "mechanical": {},
        }
        results[20] = {
            **results[20],
            "status": "error",
            "error_type": "FileNotFoundError",
            "provider_fidelity": {
                "llm": "absent",
                "retrieval": "absent",
                "structured_data": "absent",
            },
            "evidence_count": 0,
            "cost_cny": 0,
            "judge_cost_cny": 0,
            "mechanical": {},
        }
        return results

    def test_incomplete_live_cohort_builds_a_recomputable_diagnostic(self) -> None:
        proof = self._build(self._diagnostic_results())

        self.assertEqual(evaluate(proof), [])
        self.assertEqual(proof["metrics"]["evidence_reachable_rate"], 0.5)
        self.assertEqual(proof["metrics"]["total_cost_cny"], 3.3)
        self.assertEqual(proof["metrics"]["diagnostic_metric_denominator_cases"], 28)

    def test_duplicate_question_cannot_satisfy_thirty_case_count(self) -> None:
        results = self._diagnostic_results()
        results[-1] = {**results[-1], "id": "Q29"}

        proof = self._build(results)

        self.assertIn(
            "cases must be Q01-Q30 in order, exactly once",
            evaluate(proof),
        )

    def test_fixture_case_makes_the_proof_incomplete(self) -> None:
        results = self._diagnostic_results()
        results[15]["provider_fidelity"] = {
            "llm": "live",
            "retrieval": "replay",
            "structured_data": "live",
        }

        proof = self._build(results)

        self.assertEqual(proof["status"], "diagnostic_complete")
        self.assertTrue(evaluate(proof))


if __name__ == "__main__":
    unittest.main()
