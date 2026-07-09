from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path

from deepresearch_agent.agents import ExtractorAgent, PlannerAgent, ReporterAgent
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
from deepresearch_agent.settings import Settings, load_settings


class MockCompletion:
    def __init__(
        self,
        contents: list[str],
        prompt_tokens: int = 100,
        completion_tokens: int = 50,
        usage_extra: dict[str, object] | None = None,
    ) -> None:
        self.contents = contents
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.usage_extra = usage_extra or {}
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
                **self.usage_extra,
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
                global_ledger_path=Path(tmp) / "global_ledger.jsonl",
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

    def test_v4flash_price_calibration_splits_cache_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("DEEPSEEK_API_KEY=test-key\n", encoding="utf-8")
            ledger_path = Path(tmp) / "ledger.jsonl"
            client = LLMClient(
                ledger_path=ledger_path,
                budget_cny=3.0,
                completion_func=MockCompletion(
                    ["ok"],
                    prompt_tokens=1_000,
                    completion_tokens=500,
                    usage_extra={"prompt_cache_hit_tokens": 400},
                ),
                sleep_func=lambda _: None,
                env_path=env_path,
                global_ledger_path=Path(tmp) / "global_ledger.jsonl",
            )

            result = client.complete(
                role="planner",
                run_id="run-price",
                messages=[{"role": "user", "content": "hello"}],
            )
            row = json.loads(ledger_path.read_text(encoding="utf-8").splitlines()[0])

            self.assertEqual(result.prompt_cache_hit_tokens, 400)
            self.assertEqual(result.prompt_cache_miss_tokens, 600)
            self.assertAlmostEqual(result.cost_cny, 0.001608)
            self.assertAlmostEqual(row["cost_cny"], 0.001608)
            self.assertEqual(row["price_source"], "v4flash_console_calibrated_20260612")
            self.assertEqual(row["input_tokens"], row["prompt_tokens"])
            self.assertEqual(row["output_tokens"], row["completion_tokens"])

    def test_ledger_writes_global_and_task_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("DEEPSEEK_API_KEY=test-key\n", encoding="utf-8")
            task_ledger = Path(tmp) / "task" / "ledger.jsonl"
            global_ledger = Path(tmp) / "global" / "llm_ledger.jsonl"
            client = LLMClient(
                ledger_path=task_ledger,
                budget_cny=3.0,
                completion_func=MockCompletion(["ok"], prompt_tokens=10, completion_tokens=5),
                sleep_func=lambda _: None,
                env_path=env_path,
                global_ledger_path=global_ledger,
            )

            client.complete(
                role="planner",
                run_id="run-ledger",
                messages=[{"role": "user", "content": "hello"}],
            )

            self.assertTrue(task_ledger.exists())
            self.assertTrue(global_ledger.exists())
            self.assertEqual(len(task_ledger.read_text(encoding="utf-8").splitlines()), 1)
            self.assertEqual(len(global_ledger.read_text(encoding="utf-8").splitlines()), 1)
            self.assertAlmostEqual(client.ledger_total_cny(), 0.00002)

    def test_model_fallback_records_actual_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("DEEPSEEK_API_KEY=test-key\n", encoding="utf-8")
            ledger_path = Path(tmp) / "ledger.jsonl"

            def completion(**kwargs: object) -> dict:
                if kwargs["model"] == "openai/deepseek-v4-flash":
                    raise RuntimeError("model rejected")
                return {
                    "choices": [{"message": {"content": "ok"}}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                }

            client = LLMClient(
                ledger_path=ledger_path,
                budget_cny=3.0,
                completion_func=completion,
                sleep_func=lambda _: None,
                env_path=env_path,
                global_ledger_path=Path(tmp) / "global_ledger.jsonl",
            )

            result = client.complete(
                role="planner",
                run_id="run-fallback",
                messages=[{"role": "user", "content": "hello"}],
            )
            row = json.loads(ledger_path.read_text(encoding="utf-8").splitlines()[0])

            self.assertEqual(result.model, "openai/deepseek-chat")
            self.assertEqual(row["model"], "openai/deepseek-chat")

    def test_judge_role_uses_dashscope_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("DASHSCOPE_API_KEY=test-key\n", encoding="utf-8")
            observed: dict[str, object] = {}

            def completion(**kwargs: object) -> dict:
                observed.update(kwargs)
                return {
                    "choices": [{"message": {"content": "ok"}}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                }

            client = LLMClient(
                ledger_path=Path(tmp) / "task_ledger.jsonl",
                budget_cny=3.0,
                completion_func=completion,
                sleep_func=lambda _: None,
                env_path=env_path,
                global_ledger_path=Path(tmp) / "global_ledger.jsonl",
            )

            result = client.complete(
                role="judge",
                run_id="run-judge",
                messages=[{"role": "user", "content": "score"}],
            )

        self.assertEqual(result.model, "openai/qwen-plus")
        self.assertEqual(observed["api_base"], "https://dashscope.aliyuncs.com/compatible-mode/v1")
        self.assertEqual(observed["api_key"], "test-key")

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
                global_ledger_path=Path(tmp) / "global_ledger.jsonl",
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

    def test_deterministic_planner_does_not_emit_structured_requests(self) -> None:
        plan = PlannerAgent().plan("AI Agent 在财富管理行业的落地机会研究", depth_level=1)

        self.assertTrue(plan.sub_questions)
        self.assertTrue(all(not sub_question.structured_data_requests for sub_question in plan.sub_questions))

    def test_llm_planner_discards_invalid_structured_requests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("DEEPSEEK_API_KEY=test-key\n", encoding="utf-8")
            completion = MockCompletion(
                [
                    (
                        '{"topic":"宁德时代业绩研究","depth_level":1,'
                        '"sub_questions":[{"id":"finance","question":"宁德时代业绩如何？",'
                        '"search_queries":["宁德时代 业绩"],"expected_source_types":["company_report"],'
                        '"structured_data_requests":['
                        '{"capability":"financial_indicators","symbol":"300750","periods":["20241231"],'
                        '"metrics":["归母净利润"]},'
                        '{"capability":"raw_akshare","symbol":"300750"},'
                        '{"capability":"price_history","symbol":"300750"}'
                        '],"priority":5}],'
                        '"estimated_sources":2,"success_criteria":["has data"]}'
                    )
                ]
            )
            client = LLMClient(
                ledger_path=Path(tmp) / "ledger.jsonl",
                budget_cny=3.0,
                completion_func=completion,
                sleep_func=lambda _: None,
                env_path=env_path,
                global_ledger_path=Path(tmp) / "global_ledger.jsonl",
            )
            planner = PlannerAgent(
                llm_client=client,
                settings=Settings(storage_path=Path(tmp) / "research.db"),
            )

            plan = planner.plan("宁德时代业绩研究", depth_level=1, research_id="run-planner")

        self.assertEqual(len(plan.sub_questions[0].structured_data_requests), 1)
        self.assertEqual(
            plan.sub_questions[0].structured_data_requests[0].capability,
            "financial_indicators",
        )
        self.assertEqual(planner.last_stats["invalid_structured_data_requests"], 2)

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
                global_ledger_path=Path(tmp) / "global_ledger.jsonl",
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

    def test_extractor_marks_incomplete_numeric_fields_without_dropping_claim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("DEEPSEEK_API_KEY=test-key\n", encoding="utf-8")
            completion = MockCompletion(
                [
                    (
                        '{"claims":[{"claim":"宁德时代 2024 年归母净利润为 507.45 亿元",'
                        '"claim_type":"data","source_url":"https://a.example",'
                        '"extract_text":"宁德时代 2024 年归母净利润为 507.45 亿元",'
                        '"confidence":0.8,"numeric_fields":{"entity":"宁德时代",'
                        '"metric_name":"归母净利润","period":"2024","dimension":"未标注",'
                        '"value":null,"unit":"亿元"}}]}'
                    )
                ]
            )
            client = LLMClient(
                ledger_path=Path(tmp) / "ledger.jsonl",
                budget_cny=3.0,
                completion_func=completion,
                sleep_func=lambda _: None,
                env_path=env_path,
                global_ledger_path=Path(tmp) / "global_ledger.jsonl",
            )
            extractor = ExtractorAgent(llm_client=client)
            source = Source(
                title="A",
                url="https://a.example",
                source_type="company_report",
                published_at=date(2026, 1, 1),
                content="宁德时代 2024 年归母净利润为 507.45 亿元。",
            )

            evidence = extractor.extract(
                "run-4",
                SubQuestion(id="sq", question="q", search_queries=["q"]),
                [source],
            )

            self.assertEqual(len(evidence), 1)
            self.assertTrue(evidence[0].numeric_fields_incomplete)
            self.assertEqual(extractor.last_stats["incomplete_numeric_fields"], 1)

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

        report, invalid, backfilled = ReporterAgent()._render_llm_report(state, draft)

        self.assertEqual(invalid, 1)
        self.assertEqual(backfilled, 0)
        self.assertIn("[^1]", report)
        self.assertNotIn("missing", report)

    def test_reporter_backfills_missing_evidence_ids_with_best_available_citation(self) -> None:
        state = ResearchState(topic="wealth AI")
        state.plan = ResearchPlan(
            topic=state.topic,
            sub_questions=[SubQuestion(id="sq", question="q", search_queries=["q"])],
        )
        state.evidence_store = [
            Evidence(
                id="productivity",
                research_id=state.research_id,
                sub_question_id="sq",
                claim="Advisor productivity improved 18% after AI triage.",
                claim_type="data",
                source_url="https://a.example",
                source_title="A",
                source_pub_date=date(2026, 1, 1),
                extract_text="Advisor productivity improved 18% after AI triage.",
            ),
            Evidence(
                id="risk",
                research_id=state.research_id,
                sub_question_id="sq",
                claim="Human review reduced mistaken outreach escalations.",
                claim_type="fact",
                source_url="https://b.example",
                source_title="B",
                source_pub_date=date(2026, 1, 2),
                extract_text="Human review reduced mistaken outreach escalations.",
            ),
        ]
        draft = ReportDraft(
            summary="Summary",
            key_findings=[ReportClaim(text="Advisor productivity improved 18% after AI triage.")],
        )

        report, invalid, backfilled = ReporterAgent()._render_llm_report(state, draft)

        self.assertEqual(invalid, 0)
        self.assertEqual(backfilled, 1)
        self.assertIn("- Advisor productivity improved 18% after AI triage. [^1]", report)


if __name__ == "__main__":
    unittest.main()
