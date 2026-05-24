from __future__ import annotations

import unittest
from datetime import date

from deepresearch_agent.agents import Evaluator
from deepresearch_agent.schemas import Evidence, ResearchState


class EvaluatorTests(unittest.TestCase):
    def test_citation_accuracy_maps_to_evidence(self) -> None:
        state = ResearchState(topic="wealth AI")
        state.evidence_store = [
            Evidence(
                research_id=state.research_id,
                sub_question_id="a",
                claim="Advisor productivity improved 18%.",
                claim_type="data",
                source_url="https://a.example",
                source_title="A",
                source_pub_date=date(2026, 1, 1),
                extract_text="Advisor productivity improved 18%.",
            )
        ]
        state.final_report = "- Advisor productivity improved 18%. [^1]\n\n[^1]: A"
        result = Evaluator().evaluate(state)
        self.assertEqual(result.citation_accuracy, 1.0)
        self.assertEqual(result.task_success_rate, 1.0)


if __name__ == "__main__":
    unittest.main()

