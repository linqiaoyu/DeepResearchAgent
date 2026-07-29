from __future__ import annotations

import unittest

from deepresearch_agent.rag.evaluation import (
    ChunkSpan,
    SpanLabel,
    ndcg_at_k,
    recall_at_k,
    resolve_labels_to_chunks,
)


class RagEvaluationTests(unittest.TestCase):
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
