from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from deepresearch_agent.llm import LLMClient
from deepresearch_agent.llm.client import (
    CostOverrunError,
    LLMClientError,
)
from deepresearch_agent.llm_config import LLMConfig, RoleModelConfig
from deepresearch_agent.evaluation.judge import (
    EXPERIMENT_CONDITION_TERMS,
    redact_judge_report,
)
from deepresearch_agent.audit_bundle import (
    PUBLIC_EXCERPT_CHAR_LIMIT,
    export_audit_bundle,
)
from deepresearch_agent.provenance import build_run_manifest
from deepresearch_agent.reflection import (
    ReflectionLLMInsight,
    ReflectionReasoningEstimate,
    ReflectionReasoningRequest,
    Reflector,
    reflection_request_key,
)
from deepresearch_agent.settings import Settings
from deepresearch_agent.structured_output import build_structured_output
from deepresearch_agent.trajectory import (
    AgentTrajectory,
    TrajectoryRecorder,
    trajectory_recording,
)
from tests.unit.test_audit_bundle import audit_state


class StubLLMReflectionReasoner:
    """Hand-written, zero-network adapter for the 019-A recording audit."""

    def __init__(self, client: LLMClient, run_id: str) -> None:
        self.client = client
        self.run_id = run_id

    def reason(
        self,
        request: ReflectionReasoningRequest,
    ) -> ReflectionLLMInsight:
        result = self.client.complete(
            role="reflector",
            run_id=self.run_id,
            schema=ReflectionLLMInsight,
            messages=[
                {
                    "role": "user",
                    "content": request.model_dump_json(),
                }
            ],
        )
        if not isinstance(result.parsed, ReflectionLLMInsight):
            raise AssertionError("stub reflector did not return typed output")
        return result.parsed.model_copy(
            update={
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
                "cost_cny": result.cost_cny,
            }
        )

    def estimate(
        self,
        request: ReflectionReasoningRequest,
    ) -> ReflectionReasoningEstimate:
        del request
        return ReflectionReasoningEstimate(
            prompt_tokens=1_000,
            max_completion_tokens=500,
            estimated_cost_cny=0.002,
        )


class SpendingEligibilityAuditTests(unittest.TestCase):
    def test_audit_bundle_redacts_secrets_and_caps_public_excerpts(
        self,
    ) -> None:
        secret = "019A-SECRET-abcdefgh123456"
        full_extract = secret + "x" * (PUBLIC_EXCERPT_CHAR_LIMIT + 50)
        state = audit_state()
        state.topic = f"Audit {secret}"
        state.final_report = state.final_report.replace(
            "A fixture-only conclusion.",
            f"A fixture-only conclusion with {secret}.",
        )
        state.evidence_store[0].claim = f"Verified {secret}"
        state.evidence_store[0].extract_text = full_extract
        state.structured_output = build_structured_output(state)

        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            "os.environ",
            {"DEEPSEEK_API_KEY": secret},
        ):
            root = Path(tmp)
            settings = Settings(
                storage_path=root / "audit.db",
                structured_output_enabled=True,
            )
            manifest = build_run_manifest(
                state,
                settings,
                started_at=state.started_at,
                ended_at=state.updated_at,
            )
            output = root / "bundle"
            export_audit_bundle(
                state=state,
                settings=settings,
                manifest=manifest,
                output_dir=output,
            )
            all_bytes = b"".join(
                path.read_bytes()
                for path in sorted(output.iterdir())
                if path.is_file()
            )
            evidence = json.loads(
                output.joinpath("evidence.json").read_text(
                    encoding="utf-8"
                )
            )[0]

        self.assertNotIn(secret.encode(), all_bytes)
        self.assertNotIn(b"abcdefgh123456", all_bytes)
        self.assertLessEqual(
            len(evidence["extract_text"]),
            PUBLIC_EXCERPT_CHAR_LIMIT,
        )
        self.assertTrue(evidence["extract_truncated"])
        self.assertEqual(
            evidence["extract_sha256"],
            hashlib.sha256(full_extract.encode()).hexdigest(),
        )
        gitignore = Path(".gitignore").read_text(encoding="utf-8")
        for ignored in (".env", "data/runtime/", "data/raw/", "runs/"):
            self.assertIn(ignored, gitignore)

    def test_judge_report_redaction_removes_experiment_condition(self) -> None:
        report = (
            "# Report\n\n"
            "## 摘要\n"
            "Reader-visible conclusion remains.\n\n"
            "## Agent 决策记录\n\n"
            "- `reflection_signal_extraction` by `Reflector`: made_by=Reflector\n"
            "- REFLECTION_ENABLED=true; experimental_arm=treatment_arm\n\n"
            "## 决策链\n\n"
            "- reflection_result came from reflector_placeholder.\n\n"
            "## 风险\n"
            "- Reader-visible risk remains; not the control_arm or 对照组.\n"
        )

        blinded = redact_judge_report(report)

        self.assertIn("Reader-visible conclusion remains.", blinded)
        self.assertIn("Reader-visible risk remains", blinded)
        self.assertNotIn("Agent 决策记录", blinded)
        self.assertNotIn("决策链", blinded)
        for term in EXPERIMENT_CONDITION_TERMS:
            self.assertNotIn(term.lower(), blinded.lower())

    def test_environment_secret_is_redacted_from_provider_error(self) -> None:
        secret = "019A-SECRET-abcdefgh123456"
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            "os.environ",
            {"DEEPSEEK_API_KEY": secret},
        ):
            root = Path(tmp)

            def fail_with_secret(**_: object) -> dict:
                raise RuntimeError(f"provider rejected {secret}")

            client = LLMClient(
                ledger_path=root / "ledger.jsonl",
                global_ledger_path=root / "global.jsonl",
                budget_cny=1.0,
                completion_func=fail_with_secret,
                sleep_func=lambda _: None,
                env_path=root / "missing.env",
            )
            with self.assertRaises(LLMClientError) as raised:
                client.complete(
                    role="planner",
                    run_id="secret-error-audit",
                    messages=[{"role": "user", "content": "fixed"}],
                )

        self.assertNotIn(secret, str(raised.exception))
        self.assertNotIn("abcdefgh123456", str(raised.exception))
        self.assertIn("[REDACTED_API_KEY]", str(raised.exception))

    def test_provider_pricing_and_two_times_overrun_fuse(self) -> None:
        response = {
            "choices": [{"message": {"content": "fixed"}}],
            "usage": {
                "prompt_tokens": 1_000,
                "prompt_cache_hit_tokens": 200,
                "completion_tokens": 500,
                "total_tokens": 1_500,
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_path = root / ".env"
            env_path.write_text(
                "DEEPSEEK_API_KEY=zero-cost-stub-key\n"
                "DASHSCOPE_API_KEY=zero-cost-stub-key\n",
                encoding="utf-8",
            )
            client = LLMClient(
                ledger_path=root / "ledger.jsonl",
                global_ledger_path=root / "global.jsonl",
                budget_cny=1.0,
                completion_func=lambda **_: response,
                env_path=env_path,
            )

            qwen_result = client.complete(
                role="judge",
                run_id="qwen-price-audit",
                messages=[{"role": "user", "content": "fixed"}],
            )
            with self.assertRaises(CostOverrunError) as raised:
                client.complete(
                    role="planner",
                    run_id="cost-overrun-audit",
                    messages=[{"role": "user", "content": "fixed"}],
                    expected_cost_cny=0.0008,
                )

            ledger = root.joinpath("ledger.jsonl").read_text(
                encoding="utf-8"
            )

        self.assertAlmostEqual(qwen_result.cost_cny, 0.00568)
        self.assertAlmostEqual(raised.exception.actual_cny, 0.001804)
        self.assertAlmostEqual(raised.exception.estimated_cny, 0.0008)
        self.assertIn('"cost_cny": 0.001804', ledger)

    def test_reflection_replay_key_is_stable_across_run_ids(self) -> None:
        first = Reflector().reasoning_request(
            AgentTrajectory(
                run_id="run-a",
                request={"topic": "same semantic input"},
            ),
            [],
        )
        second = Reflector().reasoning_request(
            AgentTrajectory(
                run_id="run-b",
                request={"topic": "same semantic input"},
            ),
            [],
        )

        first_key = reflection_request_key(first)
        repeated_key = reflection_request_key(first)
        second_key = reflection_request_key(second)

        self.assertEqual(first_key, repeated_key)
        self.assertEqual(first_key, second_key)
        self.assertNotEqual(
            first.trajectory_summary.run_id,
            second.trajectory_summary.run_id,
        )

    def test_reflector_llm_call_records_replayable_costed_trace(self) -> None:
        response = {
            "choices": [
                {
                    "message": {
                        "content": ReflectionLLMInsight(
                            status="recorded_placeholder",
                            provider="stub_provider",
                        ).model_dump_json()
                    }
                }
            ],
            "usage": {
                "prompt_tokens": 1_000,
                "completion_tokens": 500,
                "total_tokens": 1_500,
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_path = root / ".env"
            env_path.write_text(
                "DEEPSEEK_API_KEY=zero-cost-stub-key\n",
                encoding="utf-8",
            )
            client = LLMClient(
                ledger_path=root / "ledger.jsonl",
                global_ledger_path=root / "global.jsonl",
                budget_cny=1.0,
                config=LLMConfig(
                    roles={
                        "reflector": RoleModelConfig(
                            model="openai/deepseek-v4-flash",
                            api_base="https://api.deepseek.com",
                        )
                    }
                ),
                completion_func=lambda **_: response,
                env_path=env_path,
            )
            recorder = TrajectoryRecorder(
                run_id="reflector-recording-audit",
                request={"topic": "019-A"},
            )
            reflector = Reflector(
                StubLLMReflectionReasoner(
                    client,
                    "reflector-recording-audit",
                )
            )
            trajectory = AgentTrajectory(
                run_id="reflector-recording-audit",
                request={"topic": "019-A"},
            )
            with trajectory_recording(recorder):
                reflector.reflect(trajectory, [])
            trace_path = recorder.write(root / "trajectory.json")
            payload = json.loads(trace_path.read_text(encoding="utf-8"))

        self.assertEqual(len(payload["llm_calls"]), 1)
        call = payload["llm_calls"][0]
        self.assertEqual(call["role"], "reflector")
        self.assertEqual(call["model"], "openai/deepseek-v4-flash")
        self.assertEqual(call["prompt_tokens"], 1_000)
        self.assertEqual(call["completion_tokens"], 500)
        self.assertEqual(call["response"], response["choices"][0]["message"]["content"])
        self.assertAlmostEqual(call["cost_cny"], 0.002)
        self.assertAlmostEqual(call["cost_usd"], 0.00028)
        self.assertGreaterEqual(call["latency_seconds"], 0.0)


if __name__ == "__main__":
    unittest.main()
