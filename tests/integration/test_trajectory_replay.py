from __future__ import annotations

import json
import os
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path
from unittest.mock import patch

from deepresearch_agent.llm import LLMClient
from deepresearch_agent.schemas import (
    Source,
    StructuredDataRecord,
    SymbolInfo,
)
from deepresearch_agent.settings import Settings
from deepresearch_agent.tools.disclosure_source import (
    DISCLOSURE_TOOL_SPEC,
)
from deepresearch_agent.trajectory import (
    ToolCallTrace,
    TrajectoryRecorder,
    active_trajectory_recorder,
    load_trajectory,
    trajectory_recording,
)
from deepresearch_agent.trajectory_replay import replay_trajectory
from deepresearch_agent.workflow import DeepResearchEngine


TOPICS = (
    "宁德时代 2024 年业绩与欧洲工厂扩张研究",
    "AI Agent 在财富管理行业的落地机会研究",
)


class OfflineEmptySearch:
    def search(
        self,
        query: str,
        top_k: int = 3,
        source_type: str | None = None,
    ) -> list[Source]:
        del query, top_k, source_type
        return []

    def fetch(self, url: str) -> Source | None:
        del url
        return None


class OfflineEmptyStructuredData:
    def symbol_resolve(self, company_name: str) -> SymbolInfo | None:
        del company_name
        return None

    def financial_indicators(
        self,
        symbol: str,
        periods: list[str] | None = None,
        metrics: list[str] | None = None,
    ) -> list[StructuredDataRecord]:
        del symbol, periods, metrics
        return []

    def price_history(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> list[StructuredDataRecord]:
        del symbol, start_date, end_date
        return []


class OfflineRecordingDisclosure:
    def __init__(self) -> None:
        self.source = Source(
            id="offline-moutai-annual-report",
            title="贵州茅台 2025 年年度报告",
            url="https://fixture.invalid/moutai-2025.pdf",
            source_type="disclosure_pdf",
            published_at=date(2026, 3, 30),
            content=(
                "[[PDF_PAGE=42]]\n"
                "贵州茅台2025年营业收入为1708.99亿元。\n"
                "投资者联系邮箱：ir@moutai.example"
            ),
            credibility=1.0,
            source_tier="primary",
        )

    def set_run_context(self, context: object) -> None:
        del context

    def search(
        self,
        security_code: str,
        keyword: str,
        start_date: date,
        end_date: date,
        *,
        preferred_terms: tuple[str, ...] = (),
    ) -> list[Source]:
        del preferred_terms
        inputs = {
            "security_code": security_code,
            "keyword": keyword,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        }
        recorder = active_trajectory_recorder()
        if recorder:
            recorder.record_tool_call(
                ToolCallTrace(
                    tool_spec=DISCLOSURE_TOOL_SPEC.model_dump(
                        mode="json"
                    ),
                    inputs=inputs,
                    result=[self.source.model_dump(mode="json")],
                    attempts=1,
                )
            )
        return [self.source]


class OfflineScriptedCompletion:
    def __call__(self, **kwargs):
        messages = kwargs["messages"]
        user_content = next(
            item["content"]
            for item in reversed(messages)
            if item["role"] == "user"
        )
        payload = json.loads(user_content)
        if "max_sub_questions" in payload:
            content = {
                "topic": payload["topic"],
                "depth_level": payload["depth_level"],
                "sub_questions": [
                    {
                        "id": "financial_metrics",
                        "question": payload["topic"],
                        "search_queries": ["600519 年度报告"],
                        "expected_source_types": ["official"],
                        "structured_data_requests": [],
                        "priority": 5,
                    }
                ],
                "estimated_sources": 1,
                "success_criteria": ["citation closure"],
            }
        elif "sub_question" in payload and "sources" in payload:
            source = payload["sources"][0]
            extract_text = "贵州茅台2025年营业收入为1708.99亿元。"
            content = {
                "claims": [
                    {
                        "claim": extract_text,
                        "claim_type": "data",
                        "source_url": source["url"],
                        "extract_text": extract_text,
                        "confidence": 0.99,
                        "numeric_fields": {
                            "entity": "贵州茅台",
                            "metric_name": "营业收入",
                            "period": "2025",
                            "dimension": "合并",
                            "value": 1708.99,
                            "unit": "亿元",
                        },
                    }
                ]
            }
        elif payload.get("task") == "repair_missing_evidence_ids":
            content = payload["original_draft"]
        else:
            evidence_id = payload["evidence"][0]["id"]
            sub_question_id = payload["plan"]["sub_questions"][0]["id"]
            claim = "贵州茅台2025年营业收入为1708.99亿元。"
            content = {
                "summary": "2025年营业收入已有一手年报证据。",
                "key_findings": [
                    {"text": claim, "evidence_ids": [evidence_id]}
                ],
                "detailed_analysis": [
                    {
                        "sub_question_id": sub_question_id,
                        "heading": "财务指标",
                        "claims": [
                            {
                                "text": claim,
                                "evidence_ids": [evidence_id],
                            }
                        ],
                    }
                ],
                "risks": [],
                "unverified_assumptions": [],
            }
        encoded = json.dumps(content, ensure_ascii=False)
        return {
            "choices": [{"message": {"content": encoded}}],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 10,
                "total_tokens": 20,
            },
        }


class TrajectoryReplayTests(unittest.TestCase):
    def test_strict_replay_reproduces_two_reports_byte_for_byte(self) -> None:
        for topic in TOPICS:
            with self.subTest(topic=topic), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                settings = replace(
                    Settings(
                        storage_path=root / "record.db",
                        runs_root=root / "runs",
                        as_of=date(2026, 7, 9),
                        dynamic_capability_enabled=False,
                    ),
                    trajectory_record_enabled=True,
                    structured_logging_enabled=False,
                )
                engine = DeepResearchEngine(settings=settings)
                state = engine.run(topic=topic, depth_level=1)
                engine._checkpoint_conn.close()
                path = root / "runs" / state.research_id / "trajectory.json"

                trajectory = load_trajectory(path)
                result = replay_trajectory(trajectory, mode="strict")

                self.assertEqual(result.status, "reproduced")
                self.assertEqual(result.artifact_matches, {"report.md": True})
                self.assertGreater(len(trajectory.tool_calls), 0)
                self.assertGreater(len(trajectory.node_transitions), 0)
                self.assertEqual(trajectory.llm_calls, [])
                self.assertEqual(trajectory.agent_decisions, [])
                self.assertTrue(trajectory.run_manifest_ref)
                self.assertEqual(
                    trajectory.termination.status,
                    "completed",
                )
                self.assertIn(
                    "accepted_by_tool",
                    state.metadata["external_request_budget"],
                )
                self.assertIn(
                    "rejected_by_tool",
                    state.metadata["external_request_budget"],
                )

    def test_strict_cache_miss_stops_without_inventing_response(self) -> None:
        recorder = TrajectoryRecorder(
            run_id="synthetic",
            request={
                "topic": "synthetic",
                "depth_level": 1,
                "as_of": "2026-07-09",
                "mode": "deterministic",
            },
        )

        result = replay_trajectory(
            recorder.trajectory,
            mode="strict",
            required_calls=["llm:critic"],
        )

        self.assertEqual(result.status, "cache_miss")
        self.assertEqual(result.cache_miss, "llm:critic")

    def test_strategy_replay_is_rejected_as_unimplemented(self) -> None:
        recorder = TrajectoryRecorder(
            run_id="synthetic",
            request={"mode": "deterministic"},
        )

        with self.assertRaisesRegex(
            ValueError,
            "strategy replay is not implemented",
        ):
            replay_trajectory(recorder.trajectory, mode="strategy")

    def test_sidecar_has_all_six_field_groups_and_redacts(self) -> None:
        recorder = TrajectoryRecorder(
            run_id="redact",
            request={
                "topic": "secret sk-abcdefghijklmnop",
                "numeric_18": 110105194912310021,
                "long_float": 123456789012345.67,
                "id_card": "11010519491231002X",
                "secret_keys": {
                    "sk-zyxwvutsrqponmlk": "sensitive-key-name",
                },
            },
        )
        recorder.record_tool_call(
            ToolCallTrace(
                tool_spec={"name": "fixture"},
                inputs={"token": "sk-abcdefghijklmnop"},
                result={"ok": True},
                attempts=1,
            )
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = recorder.write(Path(tmp) / "trajectory.json")
            raw = path.read_text(encoding="utf-8")
            payload = json.loads(raw)

        self.assertNotIn("sk-abcdefghijklmnop", raw)
        self.assertNotIn("sk-zyxwvutsrqponmlk", raw)
        self.assertNotIn("11010519491231002X", raw)
        self.assertIn("[REDACTED_API_KEY]", raw)
        self.assertIn("[REDACTED_ID]", raw)
        self.assertEqual(
            payload["request"]["numeric_18"],
            110105194912310021,
        )
        self.assertEqual(
            payload["request"]["long_float"],
            123456789012345.67,
        )
        for field in (
            "llm_calls",
            "tool_calls",
            "node_transitions",
            "agent_decisions",
            "run_manifest_ref",
            "artifacts",
        ):
            self.assertIn(field, payload)

    def test_llm_boundary_records_full_prompt_response_and_usage(self) -> None:
        response = {
            "choices": [{"message": {"content": "fixture response"}}],
            "usage": {
                "prompt_tokens": 4,
                "completion_tokens": 2,
                "total_tokens": 6,
            },
        }
        recorder = TrajectoryRecorder(
            run_id="llm-synthetic",
            request={"topic": "synthetic"},
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_path = root / ".env"
            env_path.write_text("DEEPSEEK_API_KEY=fixture-key\n", encoding="utf-8")
            client = LLMClient(
                ledger_path=root / "ledger.jsonl",
                global_ledger_path=root / "global.jsonl",
                budget_cny=1.0,
                completion_func=lambda **_: response,
                env_path=env_path,
            )
            with trajectory_recording(recorder):
                client.complete(
                    role="planner",
                    messages=[{"role": "user", "content": "full prompt"}],
                    run_id="llm-synthetic",
                )

        call = recorder.trajectory.llm_calls[0]
        self.assertEqual(call.prompt, [{"role": "user", "content": "full prompt"}])
        self.assertEqual(call.response, "fixture response")
        self.assertEqual(call.total_tokens, 6)
        self.assertEqual(call.model, "openai/deepseek-v4-flash")

    def test_real_shaped_llm_and_disclosure_replay_is_fully_offline(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_settings = Settings(
                storage_path=root / "record.db",
                runs_root=root / "runs",
                llm_ledger_path=root / "ledger.jsonl",
                as_of=date(2026, 7, 26),
                trajectory_record_enabled=True,
                structured_logging_enabled=False,
                run_manifest_enabled=False,
                dynamic_capability_enabled=True,
                research_min_evidence_count=1,
                research_min_independent_domains=1,
                research_min_average_confidence=0.1,
            )
            engine = DeepResearchEngine(
                settings=base_settings,
                search_tool=OfflineEmptySearch(),
                structured_data_provider=OfflineEmptyStructuredData(),
                disclosure_source=OfflineRecordingDisclosure(),
            )
            llm_settings = replace(
                base_settings,
                execution_mode="llm",
            )
            env_path = root / ".env"
            env_path.write_text(
                "DEEPSEEK_API_KEY=offline-fixture-key\n",
                encoding="utf-8",
            )
            client = LLMClient(
                ledger_path=root / "ledger.jsonl",
                global_ledger_path=root / "global-ledger.jsonl",
                budget_cny=1.0,
                completion_func=OfflineScriptedCompletion(),
                env_path=env_path,
            )
            engine.settings = llm_settings
            engine.llm_client = client
            engine.planner.settings = llm_settings
            engine.planner.llm_client = client
            engine.extractor.llm_client = client
            engine.reporter.llm_client = client
            state = engine.run(
                topic="贵州茅台 600519 2025 年营业收入研究",
                depth_level=1,
            )
            engine._checkpoint_conn.close()
            trajectory = load_trajectory(
                root
                / "runs"
                / state.research_id
                / "trajectory.json"
            )
            persisted = trajectory.model_dump_json()
            self.assertNotIn("ir@moutai.example", persisted)
            self.assertIn("[REDACTED_EMAIL]", persisted)

            with (
                patch.dict(os.environ, {}, clear=True),
                patch.object(
                    LLMClient,
                    "complete",
                    side_effect=AssertionError("live LLM forbidden"),
                ),
                patch(
                    "httpx.Client.request",
                    side_effect=AssertionError("network forbidden"),
                ),
            ):
                replay = replay_trajectory(
                    trajectory,
                    mode="strict",
                    required_calls=[
                        "llm:planner",
                        "llm:extractor",
                        "llm:reporter",
                        "tool:disclosure_source",
                    ],
                )

            mutated = trajectory.model_copy(deep=True)
            mutated.artifacts["report.md"] += "\nmutated"
            mismatch = replay_trajectory(mutated, mode="strict")

        self.assertEqual(replay.status, "reproduced", replay.cache_miss)
        self.assertEqual(replay.artifact_matches, {"report.md": True})
        self.assertEqual(trajectory.termination.status, "completed")
        self.assertEqual(
            {call.role for call in trajectory.llm_calls},
            {"planner", "extractor", "reporter"},
        )
        self.assertIn(
            "disclosure_source",
            {
                call.tool_spec.get("name")
                for call in trajectory.tool_calls
            },
        )
        self.assertEqual(mismatch.status, "mismatch")
        self.assertEqual(mismatch.artifact_matches, {"report.md": False})

    def test_unexpected_node_failure_persists_terminal_trajectory(
        self,
    ) -> None:
        failure = RuntimeError("offline planner explosion")

        class FailingPlanner:
            last_stats: dict[str, object] = {}

            def plan(self, *_args, **_kwargs):
                raise failure

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            engine = DeepResearchEngine(
                settings=Settings(
                    storage_path=root / "failure.db",
                    runs_root=root / "runs",
                    structured_logging_enabled=False,
                    run_manifest_enabled=False,
                    trajectory_record_enabled=True,
                )
            )
            engine.planner = FailingPlanner()
            with self.assertRaises(RuntimeError) as raised:
                engine.run(topic="failure trajectory", depth_level=1)
            paths = list(root.glob("runs/*/trajectory.json"))
            self.assertEqual(len(paths), 1)
            trajectory = load_trajectory(paths[0])
            checkpoint = engine.load_state(trajectory.run_id)
            engine._checkpoint_conn.close()

        self.assertIs(raised.exception, failure)
        self.assertEqual(trajectory.termination.status, "failed")
        self.assertEqual(
            trajectory.termination.error_type,
            "RuntimeError",
        )
        self.assertEqual(
            trajectory.termination.error_message,
            "offline planner explosion",
        )
        self.assertEqual(trajectory.artifacts, {})
        failed_nodes = [
            transition
            for transition in trajectory.node_transitions
            if transition.status == "failed"
        ]
        self.assertEqual(len(failed_nodes), 1)
        self.assertEqual(failed_nodes[0].node, "planner")
        self.assertEqual(
            failed_nodes[0].error_message,
            "offline planner explosion",
        )
        self.assertIsNotNone(checkpoint)
        self.assertEqual(checkpoint.status, "failed")
        self.assertIn(
            "accepted_by_tool",
            checkpoint.metadata["external_request_budget"],
        )


if __name__ == "__main__":
    unittest.main()
