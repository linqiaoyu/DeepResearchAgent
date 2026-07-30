from __future__ import annotations

import unittest
from pathlib import Path

class DockerSkillResourcesTests(unittest.TestCase):
    def test_critic_metric_resource_is_copied_into_runtime_image(self) -> None:
        root = Path(__file__).resolve().parents[2]
        dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
        resource = (
            root
            / "skills"
            / "finance-metric-normalization"
            / "resources"
            / "finance_metric_normalization.json"
        )
        self.assertTrue(resource.is_file())
        copied_directories = {
            Path(parts[1]).as_posix().rstrip("/")
            for line in dockerfile.splitlines()
            if line.startswith("COPY ")
            and len(parts := line.split()) == 3
            and not parts[1].startswith("--")
        }
        required_directory = resource.relative_to(root).parts[0]
        self.assertIn(required_directory, copied_directories)


if __name__ == "__main__":
    unittest.main()
