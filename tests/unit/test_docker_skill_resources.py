from __future__ import annotations

import unittest

from deepresearch_agent.settings import project_root


class DockerSkillResourcesTests(unittest.TestCase):
    def test_critic_metric_resource_is_copied_into_runtime_image(self) -> None:
        root = project_root()
        dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
        resource = root / "skills" / "finance-metric-normalization" / "resources" / "finance_metric_normalization.json"
        self.assertTrue(resource.is_file())
        self.assertIn("COPY skills /app/skills", dockerfile)


if __name__ == "__main__":
    unittest.main()
