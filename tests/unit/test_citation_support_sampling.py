from __future__ import annotations

import unittest

from scripts.run_citation_support_3s import _aggregate_case, majority_status


class CitationSupportSamplingTests(unittest.TestCase):
    def test_majority_status_uses_three_votes(self) -> None:
        self.assertEqual(majority_status(["supported", "unsupported", "supported"]), "supported")

    def test_majority_status_uses_ordinal_median_for_a_three_way_tie(self) -> None:
        self.assertEqual(
            majority_status(["supported", "partially_supported", "unsupported"]),
            "partially_supported",
        )

    def test_aggregate_case_scores_majority_at_claim_level(self) -> None:
        claims = [{"claim": "claim", "evidence_ids": ["1"]}]
        samples = [
            [{"claim": "claim", "evidence_ids": ["1"], "status": "supported", "reason": "a"}],
            [{"claim": "claim", "evidence_ids": ["1"], "status": "unsupported", "reason": "b"}],
            [{"claim": "claim", "evidence_ids": ["1"], "status": "supported", "reason": "c"}],
        ]

        result = _aggregate_case("Q01", claims, samples)

        self.assertEqual(result["support_rate"], 1.0)
        self.assertEqual(result["claims"][0]["status"], "supported")
        self.assertEqual(result["sample_support_rates"], [1.0, 0.0, 1.0])

    def test_aggregate_case_aligns_reordered_claims(self) -> None:
        claims = [{"claim": "first claim", "evidence_ids": []}, {"claim": "second claim", "evidence_ids": []}]
        samples = [
            [
                {"claim": "second claim", "evidence_ids": [], "status": "unsupported", "reason": "a"},
                {"claim": "first claim", "evidence_ids": [], "status": "supported", "reason": "b"},
            ],
            [
                {"claim": "first claim", "evidence_ids": [], "status": "supported", "reason": "c"},
                {"claim": "second claim", "evidence_ids": [], "status": "unsupported", "reason": "d"},
            ],
            [
                {"claim": "first claim", "evidence_ids": [], "status": "supported", "reason": "e"},
                {"claim": "second claim", "evidence_ids": [], "status": "unsupported", "reason": "f"},
            ],
        ]

        result = _aggregate_case("Q01", claims, samples)

        self.assertEqual(result["support_rate"], 0.5)
