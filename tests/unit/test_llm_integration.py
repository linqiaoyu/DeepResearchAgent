from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from deepresearch_agent.agents import ExtractorAgent, PlannerAgent, ReporterAgent
from deepresearch_agent.agents.researcher import ResearcherAgent
from deepresearch_agent.llm import (
    BudgetExceededError,
    LLMClient,
    LLMClientError,
    LLMRetryExhaustedError,
)
from deepresearch_agent.llm_config import DEFAULT_LLM_CONFIG, RoleModelConfig
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
from deepresearch_agent.tools import (
    FixtureSearchTool,
    FixtureStructuredDataProvider,
    build_capability_registry,
)
from deepresearch_agent.tools.capability_selector import (
    DeterministicCapabilitySelector,
)


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


def blocking_subprocess_worker(kwargs: dict[str, object], _result_queue: object) -> None:
    Path(str(kwargs["pid_path"])).write_text(str(os.getpid()), encoding="utf-8")
    time.sleep(5)


class LLMIntegrationTests(unittest.TestCase):
    def test_production_subprocess_timeout_terminates_worker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pid_path = Path(tmp) / "child.pid"
            started = time.perf_counter()
            with self.assertRaisesRegex(TimeoutError, "provider subprocess terminated"):
                LLMClient._call_litellm_in_subprocess(
                    kwargs={"pid_path": str(pid_path)},
                    timeout_seconds=1.0,
                    worker_target=blocking_subprocess_worker,
                )
            self.assertLess(time.perf_counter() - started, 2.5)
            child_pid = int(pid_path.read_text(encoding="utf-8"))
            with self.assertRaises(ProcessLookupError):
                os.kill(child_pid, 0)
    def test_external_call_uses_the_existing_budget_and_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = LLMClient(
                ledger_path=Path(tmp) / "ledger.jsonl",
                global_ledger_path=Path(tmp) / "global.jsonl",
                budget_cny=1.0,
                completion_func=MockCompletion(["unused"]),
            )
            client.reserve_external_call(run_id="rag-run", estimated_cost_cny=0.2)
            client.settle_external_call(
                run_id="rag-run",
                role="rag_embedding",
                call_kind="embedding",
                model="provider-model",
                input_tokens=100,
                cost_cny=0.1,
                price_source="operator-confirmed",
                latency_seconds=0.01,
                estimated_cost_cny=0.2,
                metadata={"dimensions": 1024},
            )
            row = json.loads((Path(tmp) / "ledger.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(row["call_kind"], "embedding")
        self.assertEqual(row["dimensions"], 1024)
        self.assertEqual(client.run_total_cny("rag-run"), 0.1)
    def test_complete_with_tools_records_native_tool_call_in_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("DEEPSEEK_API_KEY=test-key\n", encoding="utf-8")
            def completion(**kwargs: object) -> dict:
                self.assertIn("tools", kwargs)
                return {"choices": [{"message": {"content": "", "tool_calls": [{"function": {"name": "web_search", "arguments": "{}"}}]}}], "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}}
            ledger = Path(tmp) / "ledger.jsonl"
            result = LLMClient(ledger_path=ledger, global_ledger_path=Path(tmp) / "global.jsonl", budget_cny=3, completion_func=completion, env_path=env_path).complete_with_tools(role="capability_selector", run_id="tool-run", messages=[{"role": "user", "content": "select"}], tools=[{"type": "function", "function": {"name": "web_search", "parameters": {}}}])
            self.assertEqual(result.tool_calls[0]["function"]["name"], "web_search")
            self.assertGreater(result.total_tokens, 0)
            self.assertGreaterEqual(result.cost_cny, 0)
            self.assertGreaterEqual(result.latency_seconds, 0)
            self.assertEqual(len(ledger.read_text(encoding="utf-8").splitlines()), 1)

    def test_deterministic_planner_routes_explicit_a_share_metric_question(self) -> None:
        plan = PlannerAgent().plan("贵州茅台（600519）2025 年营业收入和毛利率是多少", depth_level=1)

        self.assertEqual(len(plan.sub_questions), 1)
        request = plan.sub_questions[0].structured_data_requests[0]
        self.assertEqual(request.capability, "financial_indicators")
        self.assertEqual(request.symbol, "600519")
        self.assertEqual(request.company_name, "贵州茅台")
        self.assertEqual(request.metrics, ["营业收入", "主营业务毛利率"])
        self.assertEqual(request.periods, ["20251231"])

    def test_budget_reservation_rejects_before_provider_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("DEEPSEEK_API_KEY=test-key\n", encoding="utf-8")
            ledger_path = Path(tmp) / "ledger.jsonl"
            completion = MockCompletion(['{"claims": []}'])
            client = LLMClient(
                ledger_path=ledger_path,
                budget_cny=0.000001,
                completion_func=completion,
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

            self.assertFalse(ledger_path.exists())
            self.assertEqual(completion.calls, 0)

    def test_concurrent_budget_reservation_allows_only_one_provider_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("DEEPSEEK_API_KEY=test-key\n", encoding="utf-8")
            provider_entered = threading.Event()
            release_provider = threading.Event()
            provider_calls = 0
            provider_lock = threading.Lock()

            def completion(**_: object) -> dict:
                nonlocal provider_calls
                with provider_lock:
                    provider_calls += 1
                provider_entered.set()
                release_provider.wait(timeout=2)
                return {
                    "choices": [{"message": {"content": "ok"}}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                }

            client = LLMClient(
                ledger_path=Path(tmp) / "ledger.jsonl",
                global_ledger_path=Path(tmp) / "global.jsonl",
                budget_cny=1.0,
                completion_func=completion,
                env_path=env_path,
            )
            outcomes: list[Exception | None] = []

            def request() -> None:
                try:
                    client.complete(
                        role="extractor",
                        run_id="shared-run",
                        messages=[{"role": "user", "content": "hello"}],
                        expected_cost_cny=0.7,
                    )
                    outcomes.append(None)
                except Exception as exc:  # Captured to assert the losing request is stopped.
                    outcomes.append(exc)

            first = threading.Thread(target=request)
            second = threading.Thread(target=request)
            first.start()
            self.assertTrue(provider_entered.wait(timeout=1))
            second.start()
            second.join(timeout=1)
            release_provider.set()
            first.join(timeout=1)

            self.assertEqual(provider_calls, 1)
            self.assertEqual(len(outcomes), 2)
            self.assertEqual(sum(item is None for item in outcomes), 1)
            self.assertTrue(any(isinstance(item, BudgetExceededError) for item in outcomes))

    def test_failed_provider_releases_budget_reservation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("DEEPSEEK_API_KEY=test-key\n", encoding="utf-8")

            def completion(**_: object) -> dict:
                raise RuntimeError("provider unavailable")

            client = LLMClient(
                ledger_path=Path(tmp) / "ledger.jsonl",
                global_ledger_path=Path(tmp) / "global.jsonl",
                budget_cny=1.0,
                completion_func=completion,
                sleep_func=lambda _: None,
                env_path=env_path,
            )

            with self.assertRaisesRegex(LLMRetryExhaustedError, "LLM call failed"):
                client.complete(
                    role="extractor",
                    run_id="failed-run",
                    messages=[{"role": "user", "content": "hello"}],
                    expected_cost_cny=0.7,
                )

            self.assertNotIn("failed-run", client._pending_costs_cny)

    def test_strict_retry_exhaustion_stops_extractor_without_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("DEEPSEEK_API_KEY=test-key\n", encoding="utf-8")

            def completion(**_: object) -> dict:
                raise RuntimeError("provider unavailable")

            client = LLMClient(
                ledger_path=Path(tmp) / "ledger.jsonl",
                global_ledger_path=Path(tmp) / "global.jsonl",
                budget_cny=1.0,
                completion_func=completion,
                sleep_func=lambda _: None,
                env_path=env_path,
                fail_on_retry_exhaustion=True,
            )
            extractor = ExtractorAgent(llm_client=client)
            sub_question = SubQuestion(
                id="strict-stop",
                question="What happened?",
                search_queries=["strict stop"],
                expected_source_types=["official"],
            )
            source = Source(
                id="strict-source",
                title="Source",
                url="https://example.test/source",
                source_type="official",
                content="A source that would yield deterministic fallback evidence.",
            )

            with self.assertRaises(LLMRetryExhaustedError):
                extractor.extract("strict-stop-run", sub_question, [source])

            self.assertEqual(extractor.last_stats, {})

    def test_main_thread_hard_timeout_interrupts_event_wait(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("DEEPSEEK_API_KEY=test-key\n", encoding="utf-8")
            entered = threading.Event()
            release = threading.Event()

            def blocking_completion(**_: object) -> dict:
                entered.set()
                release.wait(timeout=2)
                return {
                    "choices": [{"message": {"content": "late"}}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                }

            client = LLMClient(
                ledger_path=Path(tmp) / "ledger.jsonl",
                global_ledger_path=Path(tmp) / "global.jsonl",
                budget_cny=1.0,
                config=DEFAULT_LLM_CONFIG.__class__(
                    timeout_seconds=0.03,
                    max_retries=0,
                ),
                completion_func=blocking_completion,
                env_path=env_path,
            )

            started = time.perf_counter()
            with self.assertRaisesRegex(LLMClientError, "timed out"):
                client.complete(
                    role="planner",
                    run_id="timeout-run",
                    messages=[{"role": "user", "content": "hello"}],
                    expected_cost_cny=0.1,
                )

            self.assertTrue(entered.is_set())
            self.assertLess(time.perf_counter() - started, 0.5)
            self.assertNotIn("timeout-run", client._pending_costs_cny)
            self.assertFalse(
                any(thread.name == "deepresearch-llm-call" for thread in threading.enumerate())
            )
            release.set()

    def test_main_thread_deadline_does_not_leave_provider_worker_running(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("DEEPSEEK_API_KEY=test-key\n", encoding="utf-8")

            def blocking_completion(**_: object) -> dict:
                time.sleep(1)
                return {
                    "choices": [{"message": {"content": "late"}}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                }

            client = LLMClient(
                ledger_path=Path(tmp) / "ledger.jsonl",
                global_ledger_path=Path(tmp) / "global.jsonl",
                budget_cny=1.0,
                config=DEFAULT_LLM_CONFIG.__class__(
                    timeout_seconds=0.03,
                    max_retries=0,
                ),
                completion_func=blocking_completion,
                env_path=env_path,
            )

            with self.assertRaisesRegex(LLMClientError, "timed out"):
                client.complete(
                    role="planner",
                    run_id="main-thread-timeout-run",
                    messages=[{"role": "user", "content": "hello"}],
                    expected_cost_cny=0.1,
                )

            self.assertFalse(
                any(thread.name == "deepresearch-llm-call" for thread in threading.enumerate())
            )

    def test_start_run_uses_valid_ledger_index_without_rescanning_large_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger_path = root / "global.jsonl"
            row = json.dumps({"run_id": "historical-run", "cost_cny": 0.01}) + "\n"
            ledger_path.write_text(row * 100_000, encoding="utf-8")
            env_path = root / ".env"
            env_path.write_text("DEEPSEEK_API_KEY=test-key\n", encoding="utf-8")
            initial = LLMClient(
                ledger_path=root / "run.jsonl",
                global_ledger_path=ledger_path,
                budget_cny=2_000.0,
                completion_func=MockCompletion(["ok"]),
                env_path=env_path,
            )
            initial.start_run("historical-run")
            self.assertAlmostEqual(initial.run_total_cny("historical-run"), 1_000.0)

            indexed = LLMClient(
                ledger_path=root / "other-run.jsonl",
                global_ledger_path=ledger_path,
                budget_cny=2_000.0,
                completion_func=MockCompletion(["ok"]),
                env_path=env_path,
            )
            with mock.patch.object(indexed, "_rebuild_ledger_cost_index") as rebuild:
                indexed.start_run("historical-run")

            rebuild.assert_not_called()
            self.assertAlmostEqual(indexed.run_total_cny("historical-run"), 1_000.0)

    def test_corrupt_ledger_index_is_rebuilt_from_valid_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger_path = root / "global.jsonl"
            ledger_path.write_text(
                '{"run_id":"kept","cost_cny":1.25}\nnot-json\n', encoding="utf-8"
            )
            (root / "global.jsonl.index.json").write_text("not-json", encoding="utf-8")
            env_path = root / ".env"
            env_path.write_text("DEEPSEEK_API_KEY=test-key\n", encoding="utf-8")
            client = LLMClient(
                ledger_path=root / "run.jsonl",
                global_ledger_path=ledger_path,
                budget_cny=3.0,
                completion_func=MockCompletion(["ok"]),
                env_path=env_path,
            )

            client.start_run("kept")

            self.assertAlmostEqual(client.run_total_cny("kept"), 1.25)
            self.assertTrue((root / "global.jsonl.index.json").exists())

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

    def test_v4pro_official_cny_pricing_is_model_specific(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("DEEPSEEK_API_KEY=test-key\n", encoding="utf-8")
            ledger_path = Path(tmp) / "ledger.jsonl"
            pro_role = RoleModelConfig(
                model="openai/deepseek-v4-pro",
                api_base="https://api.deepseek.com",
            )
            client = LLMClient(
                ledger_path=ledger_path,
                budget_cny=3.0,
                config=DEFAULT_LLM_CONFIG.__class__(
                    roles={
                        **DEFAULT_LLM_CONFIG.roles,
                        "planner": pro_role,
                    }
                ),
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
                run_id="run-pro-price",
                messages=[{"role": "user", "content": "hello"}],
            )
            row = json.loads(
                ledger_path.read_text(encoding="utf-8").splitlines()[0]
            )

            # Official mainland-China price per million tokens is
            # cache-hit ¥0.025, cache-miss ¥3, output ¥6.
            self.assertAlmostEqual(result.cost_cny, 0.00481)
            self.assertAlmostEqual(row["cost_cny"], 0.00481)
            self.assertEqual(
                row["price_source"],
                "deepseek_official_cny_20260726",
            )

    def test_run_aggregate_reports_each_actual_price_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                "DEEPSEEK_API_KEY=test-key\nDASHSCOPE_API_KEY=test-key\n",
                encoding="utf-8",
            )
            client = LLMClient(
                ledger_path=Path(tmp) / "ledger.jsonl",
                budget_cny=3.0,
                completion_func=MockCompletion(["ok", "ok"]),
                sleep_func=lambda _: None,
                env_path=env_path,
                global_ledger_path=Path(tmp) / "global_ledger.jsonl",
            )

            for role in ("planner", "judge"):
                client.complete(
                    role=role,
                    run_id="run-mixed-pricing",
                    messages=[{"role": "user", "content": role}],
                )
            aggregate = client.aggregate_run("run-mixed-pricing")

        self.assertEqual(
            aggregate["price_sources"],
            [
                "aliyun_bailian_cn_beijing_20260725",
                "v4flash_console_calibrated_20260612",
            ],
        )
        self.assertEqual(
            aggregate["price_source"],
            "mixed:aliyun_bailian_cn_beijing_20260725,"
            "v4flash_console_calibrated_20260612",
        )

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
                config=DEFAULT_LLM_CONFIG.__class__(
                    roles={
                        **DEFAULT_LLM_CONFIG.roles,
                        "planner": RoleModelConfig(
                            model="openai/deepseek-v4-flash",
                            fallback_model="openai/deepseek-v4-flash-backup",
                            api_base="https://api.deepseek.com",
                        ),
                    },
                    pricing_by_model={
                        **DEFAULT_LLM_CONFIG.pricing_by_model,
                        "openai/deepseek-v4-flash-backup": (
                            *DEFAULT_LLM_CONFIG.pricing_by_model["openai/deepseek-v4-flash"],
                        ),
                    },
                ),
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

            self.assertEqual(result.model, "openai/deepseek-v4-flash-backup")
            self.assertEqual(row["model"], "openai/deepseek-v4-flash-backup")

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

        self.assertEqual(result.model, "openai/qwen3.7-plus")
        self.assertEqual(observed["api_base"], "https://dashscope.aliyuncs.com/compatible-mode/v1")
        self.assertEqual(observed["api_key"], "test-key")
        self.assertEqual(observed["timeout"], 300)

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

    def test_financial_planner_uses_annual_periods_and_specific_metrics(self) -> None:
        plan = PlannerAgent().plan(
            "贵州茅台（600519）2025 年营业收入、归母净利润与毛利率分别是多少？"
            "相较 2024 年的变化如何？",
            depth_level=1,
        )

        request = plan.sub_questions[0].structured_data_requests[0]
        self.assertEqual(request.periods, ["20251231", "20241231"])
        self.assertEqual(
            request.metrics,
            ["营业收入", "主营业务毛利率", "归母净利润"],
        )
        self.assertNotIn("净利润", request.metrics)
        self.assertNotIn("毛利率", request.metrics)

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

    def test_llm_planner_propagates_explicit_a_share_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("DEEPSEEK_API_KEY=test-key\n", encoding="utf-8")
            client = LLMClient(
                ledger_path=Path(tmp) / "ledger.jsonl",
                budget_cny=3.0,
                completion_func=MockCompletion([
                    '{"topic":"贵州茅台","depth_level":1,"sub_questions":['
                    '{"id":"performance","question":"业绩表现如何？",'
                    '"search_queries":["贵州茅台 业绩"],'
                    '"expected_source_types":["official"],'
                    '"structured_data_requests":[],"priority":5}],'
                    '"estimated_sources":1,"success_criteria":["traceable"]}'
                ]),
                sleep_func=lambda _: None,
                env_path=env_path,
                global_ledger_path=Path(tmp) / "global_ledger.jsonl",
            )
            planner = PlannerAgent(
                llm_client=client,
                settings=Settings(storage_path=Path(tmp) / "research.db"),
            )
            plan = planner.plan(
                "贵州茅台（600519）2025 年营业收入、归母净利润与毛利率是多少？",
                depth_level=1,
                research_id="run-planner",
            )

        request = plan.sub_questions[0].structured_data_requests[0]
        self.assertEqual(request.symbol, "600519")
        self.assertEqual(request.company_name, "贵州茅台")
        self.assertIn("归母净利润", request.metrics)
        self.assertNotIn("净利润", request.metrics)
        self.assertIn("主营业务毛利率", request.metrics)
        self.assertNotIn("毛利率", request.metrics)
        self.assertEqual(request.periods, ["20251231"])
        self.assertEqual(plan.sub_questions[0].search_queries[0], "600519 年度报告")

    def test_llm_planner_consolidates_explicit_financial_lookup_branch(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                "DEEPSEEK_API_KEY=test-key\n",
                encoding="utf-8",
            )
            completion = MockCompletion([
                '{"topic":"贵州茅台","depth_level":1,"sub_questions":['
                '{"id":"financial_data","question":"财务数据是什么？",'
                '"search_queries":["贵州茅台 财务数据"],'
                '"expected_source_types":["official"],'
                '"structured_data_requests":[],"priority":5},'
                '{"id":"change","question":"变化原因是什么？",'
                '"search_queries":["贵州茅台 变化"],'
                '"expected_source_types":["news"],'
                '"structured_data_requests":[],"priority":4},'
                '{"id":"expectations","question":"市场预期如何？",'
                '"search_queries":["贵州茅台 市场预期"],'
                '"expected_source_types":["news"],'
                '"structured_data_requests":[],"priority":3}],'
                '"estimated_sources":6,"success_criteria":["traceable"]}'
            ])
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
                settings=Settings(
                    storage_path=Path(tmp) / "research.db"
                ),
            )
            topic = (
                "贵州茅台（600519）2025 年营业收入、归母净利润与"
                "毛利率分别是多少？相较 2024 年的变化如何？"
            )

            plan = planner.plan(
                topic,
                depth_level=1,
                research_id="financial-consolidation",
            )

        self.assertEqual(len(plan.sub_questions), 1)
        self.assertEqual(plan.sub_questions[0].question, topic)
        self.assertEqual(
            plan.sub_questions[0].search_queries[0],
            "600519 年度报告",
        )
        self.assertEqual(
            plan.sub_questions[0]
            .structured_data_requests[0]
            .periods,
            ["20251231", "20241231"],
        )

    def test_llm_planner_financial_question_executes_disclosure_source(self) -> None:
        class PlannerCompletion:
            def complete(self, **_kwargs: object) -> SimpleNamespace:
                return SimpleNamespace(
                    parsed=ResearchPlan(
                        topic="贵州茅台",
                        depth_level=1,
                        sub_questions=[SubQuestion(
                            id="performance", question="业绩表现如何？",
                            search_queries=["贵州茅台 业绩"],
                            expected_source_types=["official"], priority=5,
                        )],
                        estimated_sources=1, success_criteria=["traceable"],
                    ),
                    repair_attempts=0,
                )

        class DisclosureStub:
            def __init__(self) -> None:
                self.calls: list[tuple[str, str]] = []

            def search(self, code: str, keyword: str, *_args: object, **_kwargs: object) -> list[Source]:
                self.calls.append((code, keyword))
                return [Source(
                    id="annual-report", title="贵州茅台年度报告",
                    url="https://cninfo.test/600519.pdf", source_type="disclosure_pdf",
                    published_at=date(2026, 4, 16), content="营业收入 168838102514.79",
                    source_tier="primary",
                )]

        disclosure = DisclosureStub()
        planner = PlannerAgent(
            llm_client=PlannerCompletion(),  # type: ignore[arg-type]
            settings=Settings(storage_path=Path("test.db")),
        )
        plan = planner.plan(
            "贵州茅台（600519）2025 年营业收入、归母净利润与毛利率是多少？",
            depth_level=1,
            research_id="llm-financial-pipeline",
        )
        registry = build_capability_registry(
            search_provider=FixtureSearchTool(),
            structured_data_provider=FixtureStructuredDataProvider(),
            disclosure_source=disclosure,
        )
        selection = DeterministicCapabilitySelector.from_json(
            registry, Settings(storage_path=Path("test.db")).dynamic_capability_rules_json
        ).select(
            ResearchState(topic=plan.topic), plan.sub_questions[0]
        )
        sources, *_ = ResearcherAgent(
            search_tool=FixtureSearchTool(),
            structured_data_provider=FixtureStructuredDataProvider(),
            disclosure_source=disclosure,
            as_of=date(2026, 7, 26),
        ).research_with_budget(
            plan.sub_questions[0],
            max_search_calls=None,
            enable_disclosure="disclosure_source" in selection.selected_capabilities,
            enable_web_search=False,
        )

        self.assertEqual(disclosure.calls, [("600519", "年度报告")])
        self.assertEqual(sources[0].source_tier, "primary")

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

    def test_extractor_bounds_llm_context_without_dropping_source_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("DEEPSEEK_API_KEY=test-key\n", encoding="utf-8")
            captured: dict[str, object] = {}

            def completion(**kwargs: object) -> dict[str, object]:
                captured.update(kwargs)
                return {
                    "choices": [{"message": {"content": '{"claims":[]}'}}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                }

            client = LLMClient(
                ledger_path=Path(tmp) / "ledger.jsonl",
                global_ledger_path=Path(tmp) / "global_ledger.jsonl",
                budget_cny=3.0,
                completion_func=completion,
                env_path=env_path,
            )
            sources = [
                Source(
                    title=f"Source {index}",
                    url=f"https://{index}.example",
                    source_type="official",
                    content="x" * 8_000,
                    credibility=0.8,
                )
                for index in range(20)
            ]

            extractor = ExtractorAgent(llm_client=client)
            extractor.extract(
                "bounded-context",
                SubQuestion(id="sq", question="q", search_queries=["q"]),
                sources,
            )

            messages = captured["messages"]
            assert isinstance(messages, list)
            user_message = next(message for message in messages if message["role"] == "user")
            payload = json.loads(user_message["content"])
            prompt_sources = payload["sources"]
            self.assertEqual(len(prompt_sources), 6)
            self.assertEqual(sum(len(item["content"]) for item in prompt_sources), 48_000)
            self.assertEqual(extractor.last_stats["llm_context_omitted_source_count"], 14)

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

    def test_reporter_renders_uncited_claim_when_evidence_ids_are_missing(self) -> None:
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
        self.assertEqual(backfilled, 0)
        self.assertIn("- Advisor productivity improved 18% after AI triage.", report)
        self.assertNotIn("- Advisor productivity improved 18% after AI triage. [^1]", report)

    def test_reporter_repairs_missing_evidence_ids_before_rendering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("DEEPSEEK_API_KEY=test-key\n", encoding="utf-8")
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
                )
            ]
            first_pass = {
                "summary": "Summary",
                "key_findings": [
                    {"text": "Advisor productivity improved 18% after AI triage.", "evidence_ids": []}
                ],
                "detailed_analysis": [],
                "risks": [],
                "unverified_assumptions": [],
            }
            repaired = {
                "summary": "Summary",
                "key_findings": [
                    {
                        "text": "Advisor productivity improved 18% after AI triage.",
                        "evidence_ids": ["productivity"],
                    }
                ],
                "detailed_analysis": [],
                "risks": [],
                "unverified_assumptions": [],
            }
            client = LLMClient(
                ledger_path=Path(tmp) / "ledger.jsonl",
                budget_cny=3.0,
                completion_func=MockCompletion(
                    [json.dumps(first_pass), json.dumps(repaired)],
                    prompt_tokens=10,
                    completion_tokens=5,
                ),
                sleep_func=lambda _: None,
                env_path=env_path,
                global_ledger_path=Path(tmp) / "global_ledger.jsonl",
            )

            agent = ReporterAgent(llm_client=client)
            report = agent.report(state)

        self.assertIn("- Advisor productivity improved 18% after AI triage. [^1]", report)
        self.assertEqual(agent.last_stats["citation_repair_retries"], 1)
        self.assertEqual(agent.last_stats["citation_repaired_claims"], 1)
        self.assertEqual(agent.last_stats["uncited_claims"], 0)
        self.assertEqual(agent.last_stats["claim_provenance"][0]["provenance"], "repaired")


if __name__ == "__main__":
    unittest.main()
