from __future__ import annotations

import unittest
from datetime import date

from deepresearch_agent.citations import build_footnote_maps
from deepresearch_agent.schemas import Evidence


class CitationTests(unittest.TestCase):
    def test_duplicate_source_and_claim_share_first_footnote(self) -> None:
        first = Evidence(
            id="evidence-a",
            research_id="research-1",
            sub_question_id="a",
            claim="Advisor productivity improved 18%.",
            claim_type="data",
            source_url="https://a.example",
            source_title="A",
            source_pub_date=date(2026, 1, 1),
            extract_text="Advisor productivity improved 18%.",
        )
        duplicate = Evidence(
            id="evidence-b",
            research_id="research-1",
            sub_question_id="b",
            claim="Advisor productivity improved 18%.",
            claim_type="data",
            source_url="https://a.example",
            source_title="A",
            source_pub_date=date(2026, 1, 1),
            extract_text="Advisor productivity improved 18%.",
        )

        footnotes = build_footnote_maps([first, duplicate])

        self.assertEqual(footnotes.evidence_id_to_footnote[first.id], 1)
        self.assertEqual(footnotes.evidence_id_to_footnote[duplicate.id], 1)
        self.assertIs(footnotes.footnote_to_evidence[1], first)
        self.assertEqual(footnotes.unique_refs, [first])


if __name__ == "__main__":
    unittest.main()
