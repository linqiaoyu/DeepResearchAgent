from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from deepresearch_agent.provenance.prompt_guard import verify_prompt_registry


class PromptDriftTests(unittest.TestCase):
    def test_current_hash_mismatch_triggers_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prompt_dir = Path(tmp)
            (prompt_dir / "planner.md").write_text("new", encoding="utf-8")
            errors = verify_prompt_registry(
                prompt_dir,
                {"planner.md": {"version": "1.0.0", "sha256": "old"}},
            )
        self.assertIn("content hash changed", errors[0])

    def test_hash_change_without_version_bump_triggers_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prompt_dir = Path(tmp)
            content = b"new"
            (prompt_dir / "planner.md").write_bytes(content)
            current = {
                "planner.md": {
                    "version": "1.0.0",
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            }
            previous = {"planner.md": {"version": "1.0.0", "sha256": "old"}}
            errors = verify_prompt_registry(
                prompt_dir,
                current,
                previous_registry=previous,
            )
        self.assertIn("without a version bump", errors[0])

    def test_hash_change_with_version_bump_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prompt_dir = Path(tmp)
            content = b"new"
            (prompt_dir / "planner.md").write_bytes(content)
            current = {
                "planner.md": {
                    "version": "1.1.0",
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            }
            previous = {"planner.md": {"version": "1.0.0", "sha256": "old"}}
            errors = verify_prompt_registry(
                prompt_dir,
                current,
                previous_registry=previous,
            )
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
