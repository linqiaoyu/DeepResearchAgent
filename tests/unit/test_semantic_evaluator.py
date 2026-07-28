from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from deepresearch_agent.agents import Evaluator
from deepresearch_agent.llm import BudgetExceededError
from deepresearch_agent.schemas import Evidence, ResearchState
from deepresearch_agent.semantic_judge import (
    RuntimeSemanticJudge,
    SemanticJudgeFailure,
    SemanticJudgeScore,
)
from deepresearch_agent.settings import Settings
from deepresearch_agent.workflow import DeepResearchEngine


def semantic_score() -> SemanticJudgeScore:
    return SemanticJudgeScore(
        answer_completeness=0.17,
        answer_completeness_reason="completeness adopted",
        semantic_relevance=0.29,
        semantic_relevance_reason="relevance adopted",
        answer_shape=0.61,
        answer_shape_reason="shape adopted",
        citation_support=0.43,
        citation_support_reason="citation adopted",
        semantic_faithfulness=0.73,
        semantic_faithfulness_reason="faithfulness adopted",
    )


class StubJudge:
    def __init__(
        self,
        result: SemanticJudgeScore | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result or semantic_score()
        self.error = error
        self.calls = 0

    def score(self, state: ResearchState) -> SemanticJudgeScore:
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


class StubLLMClient:
    def __init__(self, parsed: object) -> None:
        self.parsed = parsed
        self.call: dict[str, object] | None = None

    def complete(self, **kwargs: object) -> SimpleNamespace:
        self.call = kwargs
        return SimpleNamespace(parsed=self.parsed)


class SemanticEvaluatorTests(unittest.TestCase):
    def _state(self) -> ResearchState:
        state = ResearchState(topic="wealth AI")
        state.metadata["execution_mode"] = "llm"
        evidence = Evidence(
            research_id=state.research_id,
            sub_question_id="a",
            claim="Advisor productivity improved.",
            claim_type="fact",
            source_url="https://example.com/a",
            source_title="Source A",
            source_pub_date=date(2026, 1, 1),
            extract_text="Advisor productivity improved after AI rollout.",
        )
        state.evidence_store = [evidence]
        state.final_report = "- Advisor productivity improved. [^1]\n\n[^1]: Source A"
        state.report_footnote_evidence = {1: evidence.id}
        return state

    def _numeric_mismatch_state(self) -> ResearchState:
        state = ResearchState(topic="贵州茅台 2025 年营业收入")
        state.metadata["execution_mode"] = "llm"
        evidence = Evidence(
            research_id=state.research_id,
            sub_question_id="finance",
            claim="2025年营业收入为1688.38亿元。",
            claim_type="data",
            source_url="https://example.com/annual-report.pdf",
            source_title="贵州茅台2025年年度报告",
            source_page=6,
            extract_text="营业收入168,838,102,514.79元。",
            source_tier="primary",
        )
        state.evidence_store = [evidence]
        state.final_report = (
            "- 2025年营业收入为16883.81亿元。 [^1]\n\n"
            "[^1]: 贵州茅台2025年年度报告，p6"
        )
        state.report_footnote_evidence = {1: evidence.id}
        return state

    def test_typed_judge_output_is_adopted_by_runtime_evaluation(self) -> None:
        judge = StubJudge()

        result = Evaluator(semantic_judge=judge).evaluate(self._state())

        self.assertEqual(judge.calls, 1)
        self.assertEqual(result.answer_completeness, 0.17)
        self.assertEqual(result.answer_completeness_reason, "completeness adopted")
        self.assertEqual(result.semantic_relevance, 0.29)
        self.assertEqual(result.semantic_relevance_reason, "relevance adopted")
        self.assertEqual(result.answer_shape, 0.61)
        self.assertEqual(result.answer_shape_reason, "shape adopted")
        self.assertEqual(result.citation_accuracy, 0.43)
        self.assertEqual(result.citation_accuracy_reason, "citation adopted")
        self.assertEqual(result.semantic_faithfulness, 0.73)
        self.assertEqual(result.semantic_faithfulness_reason, "faithfulness adopted")

    def test_explicitly_disabled_judge_is_not_called_and_has_null_reasons(self) -> None:
        judge = StubJudge()

        result = Evaluator(
            semantic_judge=judge,
            semantic_judge_enabled=False,
        ).evaluate(self._state())

        self.assertEqual(judge.calls, 0)
        for value in (
            result.answer_completeness,
            result.semantic_relevance,
            result.answer_shape,
            result.citation_accuracy,
            result.semantic_faithfulness,
        ):
            self.assertIsNone(value)
        self.assertIn("semantic_judge_disabled", result.semantic_relevance_reason or "")

    def test_judge_failure_never_infers_scores_and_records_degradation(self) -> None:
        state = self._state()
        judge = StubJudge(error=SemanticJudgeFailure("provider_timeout"))

        result = Evaluator(semantic_judge=judge).evaluate(state)

        self.assertIsNone(result.citation_accuracy)
        self.assertIsNone(result.answer_completeness)
        self.assertIsNone(result.semantic_relevance)
        self.assertIsNone(result.answer_shape)
        self.assertIsNone(result.semantic_faithfulness)
        self.assertEqual(
            result.semantic_faithfulness_reason,
            "semantic_judge_failed: provider_timeout",
        )
        self.assertEqual(state.metadata["semantic_judge"]["status"], "failed")
        event = state.metadata["degradation_events"][-1]
        self.assertEqual(event["reason"], "semantic_judge_failed")
        self.assertIn("numeric audit remains authoritative", event["impact"])

    def test_enabled_judge_without_client_is_explicitly_unavailable(self) -> None:
        state = self._state()

        result = Evaluator(
            semantic_judge_enabled=True,
        ).evaluate(state)

        self.assertIsNone(result.citation_accuracy)
        self.assertIsNone(result.semantic_relevance)
        self.assertIn(
            "semantic_judge_unavailable",
            result.semantic_relevance_reason or "",
        )
        self.assertEqual(
            state.metadata["semantic_judge"]["status"],
            "unavailable",
        )

    def test_deterministic_mode_never_calls_optional_judge(self) -> None:
        state = self._state()
        state.metadata["execution_mode"] = "deterministic"
        judge = StubJudge()

        result = Evaluator(semantic_judge=judge).evaluate(state)

        self.assertEqual(judge.calls, 0)
        self.assertIsNone(result.answer_completeness)
        self.assertIsNone(result.answer_shape)
        self.assertIsNone(result.semantic_relevance)
        self.assertIsNone(result.semantic_faithfulness)
        self.assertIsNotNone(result.lexical_overlap)
        self.assertGreaterEqual(result.citation_density, 0.0)

    def test_semantic_all_one_cannot_override_mechanical_numeric_failure(self) -> None:
        perfect = SemanticJudgeScore(
            answer_completeness=1.0,
            answer_completeness_reason="complete",
            semantic_relevance=1.0,
            semantic_relevance_reason="relevant",
            answer_shape=1.0,
            answer_shape_reason="well shaped",
            citation_support=1.0,
            citation_support_reason="semantic support",
            semantic_faithfulness=1.0,
            semantic_faithfulness_reason="faithful",
        )

        result = Evaluator(
            semantic_judge=StubJudge(result=perfect)
        ).evaluate(self._numeric_mismatch_state())

        self.assertEqual(result.task_success_rate, 0.0)
        self.assertEqual(result.citation_accuracy, 0.0)
        self.assertEqual(result.bad_case_categories["numeric_citation_mismatch"], 1)
        self.assertIn("not delegated to the judge", result.citation_accuracy_reason or "")

    def test_budget_exception_keeps_run_level_terminal_behavior(self) -> None:
        judge = StubJudge(error=BudgetExceededError("run", 1.0, 1.1))

        with self.assertRaises(BudgetExceededError):
            Evaluator(semantic_judge=judge).evaluate(self._state())

    def test_runtime_judge_uses_typed_role_and_exact_footnote_mapping(self) -> None:
        state = self._state()
        state.final_report = (
            (state.final_report or "")
            + "\n\n## 决策链\nexperimental_arm\n\n"
            + "## 结论\ncontrol_arm metadata must be blinded."
        )
        client = StubLLMClient(semantic_score())

        result = RuntimeSemanticJudge(client).score(state)  # type: ignore[arg-type]

        self.assertEqual(result, semantic_score())
        self.assertIsNotNone(client.call)
        call = client.call or {}
        self.assertEqual(call["role"], "judge")
        self.assertIs(call["schema"], SemanticJudgeScore)
        messages = call["messages"]
        self.assertIsInstance(messages, list)
        system_prompt = messages[0]["content"]  # type: ignore[index]
        self.assertIn("do not verify exact numeric values", system_prompt)
        payload = json.loads(messages[1]["content"])  # type: ignore[index]
        self.assertEqual(
            payload["report_footnote_evidence"],
            {"1": state.evidence_store[0].id},
        )
        self.assertEqual(payload["evidence"][0]["id"], state.evidence_store[0].id)
        self.assertNotIn("experimental_arm", payload["report"])
        self.assertNotIn("control_arm", payload["report"])
        self.assertIn("[CONDITION_REDACTED]", payload["report"])

    def test_runtime_judge_rejects_disconnected_untyped_output(self) -> None:
        with self.assertRaisesRegex(
            SemanticJudgeFailure,
            "invalid_typed_output",
        ):
            RuntimeSemanticJudge(  # type: ignore[arg-type]
                StubLLMClient(None)
            ).score(self._state())

    def test_runtime_judge_reports_total_and_enforces_evidence_budgets(self) -> None:
        state = self._state()
        template = state.evidence_store[0]
        state.evidence_store = [
            template.model_copy(
                update={
                    "id": f"evidence-{index}",
                    "claim": f"claim {index} " + ("x" * 200),
                    "extract_text": f"extract {index} " + ("y" * 800),
                }
            )
            for index in range(5)
        ]
        state.report_footnote_evidence = {1: "evidence-4"}
        client = StubLLMClient(semantic_score())

        RuntimeSemanticJudge(
            client,  # type: ignore[arg-type]
            evidence_max_items=2,
            evidence_token_budget=2_000,
        ).score(state)

        call = client.call or {}
        messages = call["messages"]
        payload = json.loads(messages[1]["content"])  # type: ignore[index]
        budget = payload["evidence_budget"]
        self.assertEqual(budget["total_count"], 5)
        self.assertEqual(budget["included_count"], 2)
        self.assertEqual(budget["omitted_count"], 3)
        self.assertEqual(budget["max_items"], 2)
        self.assertLessEqual(budget["estimated_tokens"], 2_000)
        self.assertEqual(payload["evidence"][0]["id"], "evidence-4")

        tiny_client = StubLLMClient(semantic_score())
        RuntimeSemanticJudge(
            tiny_client,  # type: ignore[arg-type]
            evidence_max_items=5,
            evidence_token_budget=1,
        ).score(state)
        tiny_messages = (tiny_client.call or {})["messages"]
        tiny_payload = json.loads(  # type: ignore[index]
            tiny_messages[1]["content"]
        )
        self.assertEqual(tiny_payload["evidence"], [])
        self.assertEqual(
            tiny_payload["evidence_budget"]["mapped_evidence_omitted"],
            ["evidence-4"],
        )

    def test_usage_is_refreshed_after_judge_ledger_write(self) -> None:
        state = self._state()
        evaluator = Evaluator(semantic_judge=StubJudge())
        result = evaluator.evaluate(state)
        state.cost_used = 0.012345
        state.token_used = 321
        state.metadata["llm_usage"] = {
            "total_cost_cny": 0.06789,
            "price_source": "judge-price-source",
        }

        refreshed = evaluator.refresh_operational_metrics(result, state)

        self.assertEqual(refreshed.cost_usd, 0.0123)
        self.assertEqual(refreshed.cost_cny, 0.06789)
        self.assertEqual(refreshed.token_used, 321)
        self.assertEqual(refreshed.price_source, "judge-price-source")

    def test_engine_wires_optional_judge_into_evaluator(self) -> None:
        fake_llm_client = object()
        fake_semantic_judge = object()
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(
                storage_path=Path(tmp) / "research.db",
                execution_mode="llm",
                config_fail_fast_enabled=False,
                structured_logging_enabled=False,
                semantic_judge_enabled=True,
            )
            with (
                patch.dict(
                    os.environ,
                    {
                        "DEEPRESEARCH_SEARCH_PROVIDER": "fixture",
                        "DEEPRESEARCH_STRUCTURED_DATA_PROVIDER": "fixture",
                    },
                    clear=True,
                ),
                patch(
                    "deepresearch_agent.workflow.engine.LLMClient",
                    return_value=fake_llm_client,
                ),
                patch(
                    "deepresearch_agent.workflow.engine.RuntimeSemanticJudge",
                    return_value=fake_semantic_judge,
                ) as judge_factory,
            ):
                engine = DeepResearchEngine(settings=settings)

        judge_factory.assert_called_once_with(fake_llm_client)
        self.assertIs(engine.evaluator.semantic_judge, fake_semantic_judge)
        self.assertTrue(engine.evaluator.semantic_judge_enabled)


if __name__ == "__main__":
    unittest.main()
