from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from deepresearch_agent.provenance import (
    RunManifest,
    build_run_manifest,
    compare_manifests,
    write_run_manifest,
)
from deepresearch_agent.schemas import ResearchState
from deepresearch_agent.settings import Settings


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

    def test_flag_change_is_not_comparable(self) -> None:
        changed = manifest().model_copy(
            update={"flags": {"RUN_MANIFEST_ENABLED": False}}
        )
        self.assertIn("flags", compare_manifests(manifest(), changed).differences)

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
