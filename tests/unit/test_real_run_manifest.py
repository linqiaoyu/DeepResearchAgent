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


class RealRunManifestCheckTests(unittest.TestCase):
    def test_missing_fields_fail_closed(self) -> None:
        payload = _manifest()
        del payload["structured_data_stats"]

        self.assertTrue(validate_manifest(payload, require_all_real=False))

    def test_zero_records_fail_structured_requirement(self) -> None:
        self.assertTrue(validate_manifest(_manifest(records=0), require_all_real=False))

    def test_all_real_manifest_passes(self) -> None:
        self.assertEqual(validate_manifest(_manifest(), require_all_real=True), [])


if __name__ == "__main__":
    unittest.main()
