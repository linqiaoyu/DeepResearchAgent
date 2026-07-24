from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

from deepresearch_agent.provenance import (
    FLAG_CLASSIFICATIONS,
    RunManifest,
    build_run_manifest,
    compare_manifests,
    format_manifest_comparison,
    write_run_manifest,
)
from deepresearch_agent.schemas import ResearchState
from deepresearch_agent.settings import Settings
from deepresearch_agent.tools.fixture_search import FixtureSearchTool
from deepresearch_agent.workflow import DeepResearchEngine


def manifest() -> RunManifest:
    now = datetime(2026, 7, 24, tzinfo=timezone.utc)
    return RunManifest(
        run_id="run-1",
        started_at=now,
        ended_at=now,
        model_strings={"judge": "openai/qwen3.7-plus"},
        prompt_hashes={"judge.md": "abc"},
        retrieval_corpus_as_of=date(2026, 7, 9),
        evaluation_as_of=date(2026, 7, 9),
        config_hash="config-a",
        dependency_versions={"pydantic": "2.0"},
        domain="finance",
        mode="deterministic",
        flags={"RUN_MANIFEST_ENABLED": True},
        token_total=10,
        cost_cny_total=0.0,
    )


class RunManifestTests(unittest.TestCase):
    def test_default_settings_enable_manifest_and_record_all_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(storage_path=Path(tmp) / "research.db")
            built = build_run_manifest(
                ResearchState(topic="test"),
                settings,
                started_at=datetime(2026, 7, 24, tzinfo=timezone.utc),
            )

        self.assertTrue(settings.run_manifest_enabled)
        self.assertEqual(
            built.flags,
            {
                "TOOL_CONTRACT_ENABLED": settings.tool_contract_enabled,
                "INJECTION_GUARD_ENABLED": settings.injection_guard_enabled,
                "RUN_MANIFEST_ENABLED": settings.run_manifest_enabled,
                "CONTEXT_PACKER_ENABLED": settings.context_packer_enabled,
                "STRUCTURED_LOGGING_ENABLED": settings.structured_logging_enabled,
                "CONFIG_FAIL_FAST_ENABLED": settings.config_fail_fast_enabled,
            },
        )
        self.assertEqual(
            FLAG_CLASSIFICATIONS["RUN_MANIFEST_ENABLED"],
            "operational",
        )
        self.assertEqual(
            FLAG_CLASSIFICATIONS["PROGRESSIVE_DELIVERY_ENABLED"],
            "operational",
        )

    def test_manifest_write_failure_degrades_without_losing_completed_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(
                storage_path=Path(tmp) / "research.db",
                runs_root=Path(tmp) / "runs",
            )
            engine = DeepResearchEngine(
                settings=settings,
                search_tool=FixtureSearchTool(),
            )
            with patch(
                "deepresearch_agent.workflow.engine.write_run_manifest",
                side_effect=OSError("disk unavailable"),
            ):
                state = engine.run(topic="AI Agent 财富管理研究", depth_level=1)
            engine._checkpoint_conn.close()

        self.assertEqual(state.status, "done")
        self.assertIn(
            "run manifest sidecar unavailable",
            [event["impact"] for event in state.metadata["degradation_events"]],
        )

    def test_manifest_builder_populates_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(
                storage_path=Path(tmp) / "research.db",
                as_of=date(2026, 7, 9),
            )
            built = build_run_manifest(
                ResearchState(topic="test", token_used=12, cost_used=0.3),
                settings,
                started_at=datetime(2026, 7, 24, tzinfo=timezone.utc),
            )
        self.assertEqual(built.domain, "finance")
        self.assertEqual(built.mode, "deterministic")
        self.assertEqual(built.token_total, 12)
        self.assertEqual(built.retrieval_corpus_as_of, date(2026, 7, 9))
        self.assertIn("planner", built.model_strings)
        self.assertIn("planner.md", built.prompt_hashes)
        self.assertIn("pydantic", built.dependency_versions)
        self.assertEqual(len(built.config_hash), 64)

    def test_writer_creates_sidecar_and_redacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            item = manifest().model_copy(
                update={"degradation_events": [{"message": "sk-abcdefghijklmnop"}]}
            )
            output = write_run_manifest(item, Path(tmp))
            payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(output.name, "manifest.json")
        self.assertEqual(output.parent.name, "run-1")
        self.assertEqual(
            payload["degradation_events"][0]["message"],
            "[REDACTED_API_KEY]",
        )

    def test_equal_manifests_are_comparable(self) -> None:
        self.assertTrue(compare_manifests(manifest(), manifest()).comparable)

    def test_model_change_is_not_comparable(self) -> None:
        changed = manifest().model_copy(
            update={"model_strings": {"judge": "openai/another-judge"}}
        )
        comparison = compare_manifests(manifest(), changed)
        self.assertFalse(comparison.comparable)
        self.assertIn("model_strings", comparison.differences)

    def test_prompt_change_is_not_comparable(self) -> None:
        changed = manifest().model_copy(update={"prompt_hashes": {"judge.md": "def"}})
        self.assertIn("prompt_hashes", compare_manifests(manifest(), changed).differences)

    def test_as_of_change_is_not_comparable(self) -> None:
        changed = manifest().model_copy(
            update={"retrieval_corpus_as_of": date(2026, 7, 10)}
        )
        self.assertIn(
            "retrieval_corpus_as_of",
            compare_manifests(manifest(), changed).differences,
        )

    def test_operational_flag_change_is_informational_and_comparable(self) -> None:
        changed = manifest().model_copy(
            update={"flags": {"RUN_MANIFEST_ENABLED": False}}
        )
        comparison = compare_manifests(manifest(), changed)
        self.assertTrue(comparison.comparable)
        self.assertEqual(comparison.incomparable_reasons, {})
        self.assertIn(
            "flags.RUN_MANIFEST_ENABLED",
            comparison.informational_differences,
        )

    def test_content_affecting_flag_change_is_not_comparable(self) -> None:
        changed = manifest().model_copy(
            update={
                "flags": {
                    "RUN_MANIFEST_ENABLED": True,
                    "CONTEXT_PACKER_ENABLED": True,
                }
            }
        )
        comparison = compare_manifests(manifest(), changed)
        self.assertFalse(comparison.comparable)
        self.assertIn(
            "flags.CONTEXT_PACKER_ENABLED",
            comparison.incomparable_reasons,
        )

    def test_unknown_flag_change_is_conservatively_not_comparable(self) -> None:
        changed = manifest().model_copy(
            update={
                "flags": {
                    "RUN_MANIFEST_ENABLED": True,
                    "NEW_UNCLASSIFIED_FLAG": True,
                }
            }
        )
        comparison = compare_manifests(manifest(), changed)
        self.assertFalse(comparison.comparable)
        self.assertIn("flags.NEW_UNCLASSIFIED_FLAG", comparison.differences)

    def test_mixed_differences_are_split_into_three_output_sections(self) -> None:
        changed = manifest().model_copy(
            update={
                "model_strings": {"judge": "openai/another-judge"},
                "flags": {
                    "RUN_MANIFEST_ENABLED": False,
                    "CONTEXT_PACKER_ENABLED": True,
                },
            }
        )
        payload = format_manifest_comparison(compare_manifests(manifest(), changed))
        self.assertEqual(
            list(payload),
            [
                "incomparable_reasons",
                "informational_differences",
                "conclusion",
            ],
        )
        self.assertIn("model_strings", payload["incomparable_reasons"])
        self.assertIn(
            "flags.CONTEXT_PACKER_ENABLED",
            payload["incomparable_reasons"],
        )
        self.assertIn(
            "flags.RUN_MANIFEST_ENABLED",
            payload["informational_differences"],
        )
        self.assertFalse(payload["conclusion"]["comparable"])

    def test_dependency_change_is_not_comparable(self) -> None:
        changed = manifest().model_copy(
            update={"dependency_versions": {"pydantic": "2.1"}}
        )
        self.assertIn(
            "dependency_versions",
            compare_manifests(manifest(), changed).differences,
        )


if __name__ == "__main__":
    unittest.main()
