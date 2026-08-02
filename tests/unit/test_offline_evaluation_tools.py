from __future__ import annotations

import hashlib
import json
import subprocess
import unittest
from pathlib import Path

from deepresearch_agent.evaluation.offline import (
    calculate_offline_metrics,
    compare_result_payloads,
    validate_golden_schema,
)


ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "data" / "golden_set" / "v1"


class OfflineEvaluationToolTests(unittest.TestCase):
    def test_compare_runs_applies_significance_band(self) -> None:
        left = {"summary": {"quality": 0.80, "error_rate": 0.20, "stable": 1.0}}
        right = {"summary": {"quality": 0.82, "error_rate": 0.18, "stable": 1.01}}
        rows = {row.metric: row for row in compare_result_payloads(left, right)}
        self.assertEqual(rows["quality"].verdict, "显著改善")
        self.assertEqual(rows["error_rate"].verdict, "显著改善")
        self.assertEqual(rows["stable"].verdict, "噪声内")

    def test_compare_existing_frozen_results_is_read_only(self) -> None:
        left_path = GOLDEN / "results" / "g2_judge_v11.json"
        right_path = GOLDEN / "results" / "g3_judge_v11.json"
        before = _tree_fingerprint(GOLDEN)
        left = json.loads(left_path.read_text(encoding="utf-8"))
        right = json.loads(right_path.read_text(encoding="utf-8"))
        rows = {row.metric: row for row in compare_result_payloads(left, right)}
        after = _tree_fingerprint(GOLDEN)
        self.assertEqual(before, after)
        self.assertEqual(rows["avg_weighted_score"].verdict, "显著改善")

    def test_offline_operational_percentiles_and_rates(self) -> None:
        traces = [
            {"event": "tool_call", "ok": True},
            {"event": "tool_call", "ok": False, "degraded": True},
            {"event": "tool_call", "ok": True},
            {"event": "context_event", "dropped_count": 2},
            {"event": "context_event", "dropped_count": 0},
        ]
        ledger = [
            {"cost_cny": 1, "latency_seconds": 10},
            {"cost_cny": 2, "latency_seconds": 20},
            {"cost_cny": 3, "latency_seconds": 30},
        ]
        metrics = calculate_offline_metrics(traces, ledger)
        self.assertEqual(metrics.tool_error_rate, 0.333333)
        self.assertEqual(metrics.degradation_rate, 0.333333)
        self.assertEqual(metrics.context_overflow_rate, 0.5)
        self.assertEqual(metrics.cost_cny_p50, 2)
        self.assertEqual(metrics.cost_cny_p90, 2.8)
        self.assertEqual(metrics.latency_seconds_p90, 28)

    def test_empty_offline_inputs_are_explicit_zeroes(self) -> None:
        metrics = calculate_offline_metrics([], [])
        self.assertEqual(metrics.tool_error_rate, 0)
        self.assertEqual(metrics.cost_cny_p90, 0)
        self.assertEqual(metrics.latency_seconds_p50, 0)

    def test_frozen_golden_schema_and_shared_facts_are_valid_and_unchanged(self) -> None:
        before = _tree_fingerprint(GOLDEN)
        questions = json.loads((GOLDEN / "questions.json").read_text(encoding="utf-8"))
        revisions = json.loads((GOLDEN / "revisions_v11.json").read_text(encoding="utf-8"))
        issues = validate_golden_schema(questions, revisions)
        status = subprocess.run(
            ["git", "status", "--short", "--", "data/golden_set/v1"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
            stdin=subprocess.DEVNULL,
        )
        after = _tree_fingerprint(GOLDEN)
        self.assertEqual(issues, [])
        self.assertEqual(before, after)
        self.assertEqual(status.stdout, "")

    def test_schema_validator_reports_missing_tolerance_and_shared_mismatch(self) -> None:
        questions = {
            "questions": [
                {
                    "id": "Q01",
                    "type": "x",
                    "difficulty": "x",
                    "topic": "x",
                    "time_anchor": "x",
                    "structured_data_required": False,
                    "freeze_status": "frozen",
                    "gold": {
                        "must_include": [
                            {
                                "fact": "x",
                                "value": "one",
                                "source": "x",
                                "w": "高",
                                "source_ref": {
                                    "source_title": "x",
                                    "source_url": "https://x",
                                    "source_kind": "text",
                                    "extract_text": "x",
                                },
                            }
                        ]
                    },
                },
                {
                    "id": "Q02",
                    "type": "x",
                    "difficulty": "x",
                    "topic": "x",
                    "time_anchor": "x",
                    "structured_data_required": False,
                    "freeze_status": "frozen",
                    "gold": {
                        "must_include": [
                            {
                                "fact": "x",
                                "value": "two",
                                "source": "x",
                                "tol": "±1%",
                                "w": "高",
                                "source_ref": {
                                    "source_title": "x",
                                    "source_url": "https://x",
                                    "source_kind": "text",
                                    "extract_text": "x",
                                },
                            }
                        ]
                    },
                },
            ]
        }
        revisions = {
            "shared_fact_groups": [
                {
                    "name": "shared",
                    "slots": ["Q01s1", "Q02s1"],
                    "match_fields": ["value"],
                }
            ]
        }
        issues = validate_golden_schema(questions, revisions)
        self.assertIn("Q01s1: missing tol", issues)
        self.assertIn("shared: shared slots differ on value", issues)


def _tree_fingerprint(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


if __name__ == "__main__":
    unittest.main()
