from __future__ import annotations

import unittest

from deepresearch_agent.evaluation import (
    CitationSupportResult,
    CitationSupportVerdict,
    JudgeScore,
    median_judge_score,
)


class JudgeTests(unittest.TestCase):
    def test_judge_score_uses_locked_weights(self) -> None:
        score = JudgeScore(
            fact_coverage=1.0,
            fact_accuracy=0.8,
            citation_support=0.6,
            synthesis_balance=0.4,
        )

        self.assertEqual(score.weighted_score, 0.76)

    def test_median_judge_score_aggregates_each_dimension(self) -> None:
        samples = [
            JudgeScore(fact_coverage=0.1, fact_accuracy=0.2, citation_support=0.3, synthesis_balance=0.4),
            JudgeScore(fact_coverage=0.9, fact_accuracy=0.8, citation_support=0.7, synthesis_balance=0.6),
            JudgeScore(fact_coverage=0.5, fact_accuracy=0.4, citation_support=0.5, synthesis_balance=0.8),
        ]

        score = median_judge_score(samples)

        self.assertEqual(score.fact_coverage, 0.5)
        self.assertEqual(score.fact_accuracy, 0.4)
        self.assertEqual(score.citation_support, 0.5)
        self.assertEqual(score.synthesis_balance, 0.6)

    def test_citation_support_rate_aggregates_three_states(self) -> None:
        result = CitationSupportResult(
            verdicts=[
                CitationSupportVerdict(claim="a", evidence_ids=["e1"], status="supported", reason="ok"),
                CitationSupportVerdict(
                    claim="b",
                    evidence_ids=["e2"],
                    status="partially_supported",
                    reason="partial",
                ),
                CitationSupportVerdict(claim="c", evidence_ids=["e3"], status="unsupported", reason="no"),
            ]
        )

        self.assertEqual(result.support_rate, 0.5)


if __name__ == "__main__":
    unittest.main()
