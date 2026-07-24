from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class DeploymentHardeningTests(unittest.TestCase):
    def test_dockerfile_is_multistage_non_root_pinned_and_healthy(self) -> None:
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertGreaterEqual(dockerfile.count("FROM python:3.12.10-slim-bookworm"), 2)
        self.assertIn(" AS builder", dockerfile)
        self.assertIn(" AS runtime", dockerfile)
        self.assertIn("USER deepresearch", dockerfile)
        self.assertIn("HEALTHCHECK", dockerfile)
        self.assertIn("/healthz", dockerfile)

    def test_dockerignore_excludes_secrets_and_runtime_data(self) -> None:
        entries = set((ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines())
        self.assertTrue({".env", "data/runtime", "_collab", ".git"}.issubset(entries))

    def test_ci_is_offline_deterministic_and_has_required_gates(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("DEEPRESEARCH_MODE: deterministic", workflow)
        self.assertIn("DEEPRESEARCH_SEARCH_PROVIDER: fixture", workflow)
        self.assertIn("ruff check src tests scripts", workflow)
        self.assertIn("check_prompt_drift.py", workflow)
        self.assertNotIn("secrets.", workflow)


if __name__ == "__main__":
    unittest.main()
