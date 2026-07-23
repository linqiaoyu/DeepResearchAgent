from __future__ import annotations

import io
import json
import unittest
from pathlib import Path

from deepresearch_agent.config_validation import (
    ConfigurationError,
    validate_required_configuration,
)
from deepresearch_agent.observability import JsonLogger, correlation_context
from deepresearch_agent.settings import Settings


class ObservabilityAndConfigTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
