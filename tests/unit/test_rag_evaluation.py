from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

from deepresearch_agent.rag.evaluation import (
    ChunkSpan,
    SpanLabel,
    ndcg_at_k,
    recall_at_k,
    resolve_labels_to_chunks,
)
from deepresearch_agent.rag.__main__ import _write_benchmark_report, build_benchmark_report


class RagEvaluationTests(unittest.TestCase):
    def test_benchmark_schema_reports_missing_evidence_as_null(self) -> None:
        report = build_benchmark_report({"active_chunks": 0})
        self.assertEqual(report["active_chunks"], 0)
        self.assertIsNone(report["metrics"]["recall_at_20"])
        self.assertIn("no_active_chunks", report["unavailable_reasons"])

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_benchmark_report(report, root / "benchmark.json", root / "benchmark.md")
            self.assertIn('"recall_at_20": null', (root / "benchmark.json").read_text())
            self.assertIn("## Unavailable evidence", (root / "benchmark.md").read_text())

    def test_evaluation_document_records_the_retrieval_metric_contract(self) -> None:
        root = Path(__file__).resolve().parents[2]
        document = (root / "docs" / "evaluation.md").read_text(encoding="utf-8")

        self.assertIn("### Retrieval metric contract (047)", document)
        self.assertIn("Recall@20", document)
        self.assertIn("nDCG@10", document)
        self.assertIn("fail below `+0.10`", document)

    def test_span_overlap_marks_both_boundary_chunks_relevant(self) -> None:
        labels = [SpanLabel("doc", 9, 11, 2)]
        chunks = [ChunkSpan("left", "doc", 0, 10), ChunkSpan("right", "doc", 10, 20)]
        self.assertEqual(resolve_labels_to_chunks(labels, chunks), {"left": 2, "right": 2})

    def test_metrics_follow_frozen_gain_and_discount_contract(self) -> None:
        relevant = {"a": 2, "b": 1}
        self.assertEqual(recall_at_k(["a", "x"], relevant, 2), 0.5)
        self.assertEqual(ndcg_at_k(["a", "b"], relevant, 2), 1.0)


if __name__ == "__main__":
    unittest.main()
