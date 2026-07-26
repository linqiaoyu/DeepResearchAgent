from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from deepresearch_agent.config_validation import (
    ConfigurationError,
    validate_required_configuration,
)
from deepresearch_agent.observability import JsonLogger, correlation_context
from deepresearch_agent.settings import Settings, load_settings


class ObservabilityAndConfigTests(unittest.TestCase):
    def test_structured_logging_is_enabled_by_default(self) -> None:
        self.assertTrue(Settings(storage_path=Path("test.db")).structured_logging_enabled)

    def test_configuration_validation_is_enabled_by_default(self) -> None:
        self.assertTrue(Settings(storage_path=Path("test.db")).config_fail_fast_enabled)

    def test_agent_ablation_flags_are_explicit_and_env_configurable(self) -> None:
        defaults = Settings(storage_path=Path("test.db"))
        self.assertTrue(defaults.critic_enabled)
        self.assertTrue(defaults.extractor_enabled)
        self.assertTrue(defaults.procedural_memory_enabled)
        with patch.dict(
            "os.environ",
            {
                "CRITIC_ENABLED": "false",
                "EXTRACTOR_ENABLED": "false",
                "PROCEDURAL_MEMORY_ENABLED": "false",
            },
        ):
            configured = load_settings()
        self.assertFalse(configured.critic_enabled)
        self.assertFalse(configured.extractor_enabled)
        self.assertFalse(configured.procedural_memory_enabled)

    def test_json_logger_carries_correlation_and_redacts(self) -> None:
        stream = io.StringIO()
        logger = JsonLogger(enabled=True, stream=stream)
        with correlation_context(
            run_id="run-1",
            node="researcher",
            tool_call="web_search",
            llm_call="extractor",
        ):
            logger.event("call_finished", detail="sk-abcdefghijklmnop")
        payload = json.loads(stream.getvalue())
        self.assertEqual(payload["run_id"], "run-1")
        self.assertEqual(payload["node"], "researcher")
        self.assertEqual(payload["tool_call"], "web_search")
        self.assertEqual(payload["llm_call"], "extractor")
        self.assertEqual(payload["detail"], "[REDACTED_API_KEY]")

    def test_disabled_logger_has_no_output(self) -> None:
        stream = io.StringIO()
        JsonLogger(enabled=False, stream=stream).event("ignored")
        self.assertEqual(stream.getvalue(), "")

    def test_logger_sink_failure_does_not_break_the_caller(self) -> None:
        class BrokenStream:
            def write(self, _: str) -> int:
                raise OSError("sink unavailable")

            def flush(self) -> None:
                raise AssertionError("flush must not run after write failure")

        JsonLogger(enabled=True, stream=BrokenStream()).event("ignored_sink_failure")

    def test_fail_fast_lists_all_missing_configuration(self) -> None:
        settings = Settings(
            storage_path=Path("test.db"),
            execution_mode="llm",
            config_fail_fast_enabled=True,
        )
        environ = {
            "DEEPRESEARCH_SEARCH_PROVIDER": "tavily",
            "DEEPRESEARCH_REQUIRE_DEMO_OWNER": "true",
        }
        with self.assertRaises(ConfigurationError) as raised:
            validate_required_configuration(settings, environ)
        self.assertEqual(
            raised.exception.missing,
            [
                "DEEPRESEARCH_DEMO_OWNER_TOKEN",
                "DEEPSEEK_API_KEY",
                "TAVILY_API_KEY",
            ],
        )

    def test_deterministic_fixture_configuration_needs_no_keys(self) -> None:
        settings = Settings(storage_path=Path("test.db"))
        validate_required_configuration(
            settings,
            {
                "DEEPRESEARCH_SEARCH_PROVIDER": "fixture",
                "DEEPRESEARCH_STRUCTURED_DATA_PROVIDER": "fixture",
            },
        )

    def test_fail_fast_reads_deepseek_key_from_project_env_file(self) -> None:
        settings = Settings(
            storage_path=Path("test.db"),
            execution_mode="llm",
        )
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("DEEPSEEK_API_KEY=test-key\n", encoding="utf-8")
            validate_required_configuration(settings, env_path=env_path)


if __name__ == "__main__":
    unittest.main()
