from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date
from pathlib import Path

from deepresearch_agent.agents import ExtractorAgent, ReporterAgent
from deepresearch_agent.llm import BudgetExceededError, LLMClient
from deepresearch_agent.schemas import (
    Evidence,
    ReportClaim,
    ReportDraft,
    ResearchPlan,
    ResearchState,
    Source,
    SubQuestion,
)
from deepresearch_agent.settings import load_settings


class MockCompletion:
    def __init__(self, contents: list[str], prompt_tokens: int = 100, completion_tokens: int = 50) -> None:
        self.contents = contents
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.calls = 0

    def __call__(self, **_: object) -> dict:
        content = self.contents[min(self.calls, len(self.contents) - 1)]
        self.calls += 1
        return {
            "choices": [{"message": {"content": content}}],
            "usage": {
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "total_tokens": self.prompt_tokens + self.completion_tokens,
            },
        }


class LLMIntegrationTests(unittest.TestCase):
    def test_budget_fuse_raises_after_recording_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("DEEPSEEK_API_KEY=test-key\n", encoding="utf-8")
            ledger_path = Path(tmp) / "ledger.jsonl"
            client = LLMClient(
                ledger_path=ledger_path,
                budget_cny=0.000001,
                completion_func=MockCompletion(['{"claims": []}']),
                sleep_func=lambda _: None,
                env_path=env_path,
            )

            with self.assertRaises(BudgetExceededError):
                client.complete(
                    role="extractor",
                    run_id="run-1",
                    schema=None,
                    messages=[{"role": "user", "content": "hello"}],
                )

            self.assertTrue(ledger_path.exists())
            self.assertIn('"role": "extractor"', ledger_path.read_text(encoding="utf-8"))

    def test_structured_parse_failure_repairs_and_records_two_calls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("DEEPSEEK_API_KEY=test-key\n", encoding="utf-8")
            ledger_path = Path(tmp) / "ledger.jsonl"
            completion = MockCompletion(["not-json", '{"claims": []}'])
            client = LLMClient(
                ledger_path=ledger_path,
                budget_cny=3.0,
                completion_func=completion,
                sleep_func=lambda _: None,
                env_path=env_path,
            )

            from deepresearch_agent.schemas import ExtractedClaims

            result = client.complete(
                role="extractor",
                run_id="run-2",
                schema=ExtractedClaims,
                messages=[{"role": "user", "content": "extract"}],
            )

            self.assertEqual(completion.calls, 2)
            self.assertEqual(result.repair_attempts, 1)
            self.assertEqual(len(ledger_path.read_text(encoding="utf-8").splitlines()), 2)

    def test_mode_switch_defaults_to_deterministic_and_accepts_llm_env(self) -> None:
        old_value = os.environ.get("DEEPRESEARCH_MODE")
        try:
            os.environ.pop("DEEPRESEARCH_MODE", None)
            self.assertEqual(load_settings().execution_mode, "deterministic")
            os.environ["DEEPRESEARCH_MODE"] = "llm"
            self.assertEqual(load_settings().execution_mode, "llm")
        finally:
            if old_value is None:
                os.environ.pop("DEEPRESEARCH_MODE", None)
            else:
                os.environ["DEEPRESEARCH_MODE"] = old_value

    def test_extractor_discards_claim_when_extract_text_is_not_verbatim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("DEEPSEEK_API_KEY=test-key\n", encoding="utf-8")
            completion = MockCompletion(
                [
                    (
                        '{"claims":[{"claim":"A valid claim","claim_type":"fact",'
                        '"source_url":"https://a.example","extract_text":"verbatim source text",'
                        '"confidence":0.8},{"claim":"Invalid","claim_type":"fact",'
                        '"source_url":"https://a.example","extract_text":"not in source",'
                        '"confidence":0.8}]}'
                    )
                ]
            )
            client = LLMClient(
                ledger_path=Path(tmp) / "ledger.jsonl",
                budget_cny=3.0,
                completion_func=completion,
                sleep_func=lambda _: None,
                env_path=env_path,
            )
            extractor = ExtractorAgent(llm_client=client)
            source = Source(
                title="A",
                url="https://a.example",
                source_type="official",
                published_at=date(2026, 1, 1),
                content="This is verbatim source text for extraction.",
            )

            evidence = extractor.extract(
                "run-3",
                SubQuestion(id="sq", question="q", search_queries=["q"]),
                [source],
            )

            self.assertEqual(len(evidence), 1)
            self.assertEqual(extractor.last_stats["invalid_extract_text"], 1)

    def test_reporter_reference_validation_counts_invalid_ids(self) -> None:
        state = ResearchState(topic="wealth AI")
        state.plan = ResearchPlan(
            topic=state.topic,
            sub_questions=[SubQuestion(id="sq", question="q", search_queries=["q"])],
        )
        state.evidence_store = [
            Evidence(
                id="e1",
                research_id=state.research_id,
                sub_question_id="sq",
                claim="Advisor productivity improved 18%.",
                claim_type="data",
                source_url="https://a.example",
                source_title="A",
                source_pub_date=date(2026, 1, 1),
                extract_text="Advisor productivity improved 18%.",
            )
        ]
        draft = ReportDraft(
            summary="Summary",
            key_findings=[ReportClaim(text="Finding", evidence_ids=["e1", "missing"])],
        )

        report, invalid = ReporterAgent()._render_llm_report(state, draft)

        self.assertEqual(invalid, 1)
        self.assertIn("[^1]", report)
        self.assertNotIn("missing", report)


if __name__ == "__main__":
    unittest.main()
