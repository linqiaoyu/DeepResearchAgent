from __future__ import annotations

import difflib
import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "snapshot_run.py"
SPEC = importlib.util.spec_from_file_location("snapshot_run", SCRIPT)
assert SPEC and SPEC.loader
snapshot_run = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(snapshot_run)


class SnapshotNormalizationTest(unittest.TestCase):
    def test_normalizes_nondeterministic_fields(self) -> None:
        payload = {
            "run_id": "123e4567-e89b-42d3-a456-426614174000",
            "started_at": "2026-07-24T12:00:00Z",
            "latency_seconds": 3.2,
            "path": "/tmp/example/research.db",
            "random_seed": 123,
        }

        normalized = snapshot_run.normalize(payload)

        self.assertEqual(normalized["run_id"], "<normalized-id>")
        self.assertEqual(normalized["started_at"], "<normalized-timestamp>")
        self.assertEqual(normalized["latency_seconds"], 0)
        self.assertEqual(normalized["path"], "<normalized-path>")
        self.assertNotIn("random_seed", normalized)

    def test_normalizes_uuid_partially_redacted_as_phone(self) -> None:
        value = "20c0cc5e-2f93-5743-b763-f[REDACTED_PHONE]"

        self.assertEqual(snapshot_run.normalize(value), "<normalized-id>")


class WorkflowCharacterizationTest(unittest.TestCase):
    maxDiff = None

    def test_golden_workflow_outputs_are_byte_identical(self) -> None:
        for case in snapshot_run.SNAPSHOT_CASES:
            topic = case["topic"]
            filename = case["filename"]
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as temp_dir:
                actual = snapshot_run.encode_snapshot(
                    snapshot_run.build_snapshot(
                        topic,
                        runs_root=Path(temp_dir) / "runs",
                        settings_overrides=case.get("settings_overrides"),
                    )
                )
                golden_path = ROOT / "tests" / "golden_output" / filename
                expected = golden_path.read_text(encoding="utf-8")
                if actual != expected:
                    diff = "".join(
                        difflib.unified_diff(
                            expected.splitlines(keepends=True),
                            actual.splitlines(keepends=True),
                            fromfile=str(golden_path),
                            tofile=f"actual:{topic}",
                        )
                    )
                    self.fail(f"Normalized workflow snapshot changed:\n{diff}")


if __name__ == "__main__":
    unittest.main()
