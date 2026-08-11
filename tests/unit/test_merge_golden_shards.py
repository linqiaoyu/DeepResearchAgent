from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from merge_golden_shards import merge  # noqa: E402


class MergeGoldenShardsTests(unittest.TestCase):
    def _shard(self, root: Path, name: str, results: list[dict[str, str]]) -> Path:
        path = root / name
        path.write_text(
            json.dumps(
                {
                    "generation": "F01",
                    "gold_version": "v1.1",
                    "evaluation_as_of": "2026-07-12",
                    "judge_samples": 3,
                    "state_path_map": None,
                    "provider_fidelity": {
                        "llm": "live",
                        "retrieval": "live",
                        "structured_data": "live",
                    },
                    "results": results,
                }
            ),
            encoding="utf-8",
        )
        return path

    def test_exact_once_shards_merge(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [
                self._shard(root, "one.json", [{"id": "Q01", "status": "done"}]),
                self._shard(root, "two.json", [{"id": "Q02", "status": "error"}]),
            ]

            payload = merge(paths, round_id="149", expected=2)

        self.assertEqual(payload["coverage"], "2/2")
        self.assertEqual(payload["error_questions"], ["Q02"])
        self.assertEqual(payload["superseded_failures"], [])
        self.assertEqual(payload["provider_fidelity"]["retrieval"], "live")

    def test_completed_rerun_cannot_supersede_a_failure_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [
                self._shard(root, "one.json", [{"id": "Q01", "status": "error"}]),
                self._shard(root, "two.json", [{"id": "Q01", "status": "done"}]),
            ]

            with self.assertRaisesRegex(ValueError, "scored more than once"):
                merge(paths, round_id="149", expected=1)

    def test_legacy_supersession_requires_explicit_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [
                self._shard(root, "one.json", [{"id": "Q01", "status": "error"}]),
                self._shard(root, "two.json", [{"id": "Q01", "status": "done"}]),
            ]

            payload = merge(
                paths,
                round_id="historical",
                expected=1,
                allow_failed_supersession=True,
            )

        self.assertEqual(payload["results"][0]["status"], "done")
        self.assertEqual(len(payload["superseded_failures"]), 1)

    def test_shards_with_different_fidelity_cannot_be_merged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = self._shard(root, "one.json", [{"id": "Q01", "status": "done"}])
            second = self._shard(root, "two.json", [{"id": "Q02", "status": "done"}])
            payload = json.loads(second.read_text(encoding="utf-8"))
            payload["provider_fidelity"]["retrieval"] = "replay"
            second.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "metadata mismatch"):
                merge([first, second], round_id="149", expected=2)


if __name__ == "__main__":
    unittest.main()
