from __future__ import annotations

import unittest

from scripts.check_real_run_manifest import validate_manifest


def _manifest(*, records: int = 1) -> dict[str, object]:
    return {
        "provider_usage": {
            "llm": 1,
            "search": 1,
            "disclosure": 1,
            "structured_data": records,
        },
        "structured_data_stats": {
            "financial": {
                "requests": 1,
                "executed_requests": 1,
                "records": records,
                "symbol_resolution_failures": 0,
                "execution_failures": 0,
            }
        },
        "actual_provider_fidelity": {
            "llm": "real",
            "search": "real",
            "disclosure": "real",
            "structured_data": "real",
        },
        "actual_realness": "real",
    }


def _active_t8_manifest() -> dict[str, object]:
    return {
        "provider_usage": {
            "llm": 1,
            "search": 1,
            "rag_search": 1,
            "disclosure": 0,
            "structured_data": 0,
        },
        "structured_data_stats": {
            "finance": {
                "requests": 0,
                "executed_requests": 0,
                "records": 0,
                "symbol_resolution_failures": 0,
                "execution_failures": 0,
            }
        },
        "actual_provider_fidelity": {
            "llm": "real",
            "search": "real",
            "rag_search": "real",
            "disclosure": "unused",
            "structured_data": "unused",
        },
        "actual_realness": "mixed",
        "degradation_events": [],
    }


class RealRunManifestCheckTests(unittest.TestCase):
    def test_missing_fields_fail_closed(self) -> None:
        payload = _manifest()
        del payload["structured_data_stats"]

        self.assertTrue(validate_manifest(payload, require_all_real=False))

    def test_zero_records_fail_structured_requirement(self) -> None:
        self.assertTrue(validate_manifest(_manifest(records=0), require_all_real=False))

    def test_all_real_manifest_passes(self) -> None:
        self.assertEqual(validate_manifest(_manifest(), require_all_real=True), [])

    def test_active_t8_manifest_allows_explicitly_unused_optional_providers(self) -> None:
        self.assertEqual(
            validate_manifest(
                _active_t8_manifest(), require_all_real=False, require_active_real=True
            ),
            [],
        )

    def test_active_t8_manifest_rejects_fixture_active_provider(self) -> None:
        payload = _active_t8_manifest()
        payload["actual_provider_fidelity"]["rag_search"] = "fixture"  # type: ignore[index]

        failures = validate_manifest(payload, require_all_real=False, require_active_real=True)

        self.assertIn("actual_provider_fidelity.rag_search='fixture'", failures)

    def test_active_t8_manifest_rejects_degraded_unused_optional_provider(self) -> None:
        payload = _active_t8_manifest()
        payload["degradation_events"].append({"tool": "structured_data_provider"})  # type: ignore[index]

        failures = validate_manifest(payload, require_all_real=False, require_active_real=True)

        self.assertIn("optional_provider_degradation.structured_data=1", failures)


if __name__ == "__main__":
    unittest.main()
