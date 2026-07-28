from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from deepresearch_agent.provenance.manifest import FLAG_CLASSIFICATIONS
from deepresearch_agent.settings import (
    Settings,
    boolean_setting_defaults,
    load_settings,
)
from scripts.sync_agents_settings import (
    BEGIN_MARKER,
    END_MARKER,
    ENV_BEGIN_MARKER,
    ENV_END_MARKER,
    check_document,
    check_environment_document,
    check_readme_document,
    expected_environment_document,
    expected_readme_document,
    render_environment_block,
    render_generated_block,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class SettingsDocumentationTests(unittest.TestCase):
    def test_generated_agents_block_matches_settings_and_manifest(self) -> None:
        agents_path = PROJECT_ROOT / "AGENTS.md"
        self.assertTrue(check_document(agents_path))
        document = agents_path.read_text(encoding="utf-8")
        self.assertEqual(document.count(BEGIN_MARKER), 1)
        self.assertEqual(document.count(END_MARKER), 1)
        self.assertIn(render_generated_block(), document)

    def test_generated_environment_defaults_match_settings(self) -> None:
        env_path = PROJECT_ROOT / ".env.example"
        self.assertTrue(check_environment_document(env_path))
        document = env_path.read_text(encoding="utf-8")
        self.assertEqual(document.count(ENV_BEGIN_MARKER), 1)
        self.assertEqual(document.count(ENV_END_MARKER), 1)
        self.assertIn(render_environment_block(), document)
        self.assertIn(
            "DEEPRESEARCH_DYNAMIC_CAPABILITY_RULES_JSON="
            + Settings(
                storage_path=Path("test.db")
            ).dynamic_capability_rules_json,
            document,
        )

    def test_readme_boolean_default_claims_match_settings(self) -> None:
        self.assertTrue(check_readme_document(PROJECT_ROOT / "README.md"))

    def test_environment_and_readme_drift_are_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env.example"
            env_path.write_text(
                (PROJECT_ROOT / ".env.example")
                .read_text(encoding="utf-8")
                .replace(
                    "DYNAMIC_CAPABILITY_ENABLED=true",
                    "DYNAMIC_CAPABILITY_ENABLED=false",
                ),
                encoding="utf-8",
            )
            readme_path = Path(tmp) / "README.md"
            readme_path.write_text(
                "default `DYNAMIC_CAPABILITY_ENABLED=false`\n",
                encoding="utf-8",
            )

            self.assertNotEqual(
                env_path.read_text(encoding="utf-8"),
                expected_environment_document(env_path),
            )
            self.assertNotEqual(
                readme_path.read_text(encoding="utf-8"),
                expected_readme_document(readme_path),
            )

    def test_dynamic_capability_rules_drift_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env.example"
            env_path.write_text(
                (PROJECT_ROOT / ".env.example")
                .read_text(encoding="utf-8")
                .replace('"event": ["disclosure_source", "web_fetch", "web_search"],', ""),
                encoding="utf-8",
            )

            self.assertNotEqual(
                env_path.read_text(encoding="utf-8"),
                expected_environment_document(env_path),
            )

    def test_effective_boolean_defaults_match_dataclass_defaults(self) -> None:
        expected = boolean_setting_defaults()
        with patch.dict(os.environ, {}, clear=True):
            effective = load_settings()
        for environment_name, expected_value in expected.items():
            attribute = environment_name.lower()
            self.assertEqual(
                getattr(effective, attribute),
                expected_value,
                environment_name,
            )

    def test_every_documented_boolean_has_an_effective_environment_override(self) -> None:
        defaults = boolean_setting_defaults()
        for environment_name, default_value in defaults.items():
            override = "false" if default_value else "true"
            with patch.dict(os.environ, {environment_name: override}, clear=True):
                effective = load_settings()
            self.assertEqual(
                getattr(effective, environment_name.lower()),
                not default_value,
                environment_name,
            )

    def test_every_boolean_setting_has_a_manifest_classification(self) -> None:
        self.assertEqual(set(boolean_setting_defaults()), set(FLAG_CLASSIFICATIONS))

    def test_ci_runs_the_settings_documentation_check(self) -> None:
        workflow = (PROJECT_ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("python scripts/gate.py", workflow)

    def test_direct_settings_default_documents_dynamic_capability_as_enabled(self) -> None:
        self.assertTrue(Settings(storage_path=Path("test.db")).dynamic_capability_enabled)
        self.assertTrue(boolean_setting_defaults()["DYNAMIC_CAPABILITY_ENABLED"])


if __name__ == "__main__":
    unittest.main()
