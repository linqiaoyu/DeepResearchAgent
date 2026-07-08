from __future__ import annotations

import tempfile
import unittest
import json
from datetime import date
from pathlib import Path

from deepresearch_agent.schemas import Source
from deepresearch_agent.tools import (
    RecordingReplayMiss,
    RecordingSearchProvider,
    build_search_provider,
    normalize_query_key,
)


class FakeLiveProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, str | None]] = []

    def search(self, query: str, top_k: int = 3, source_type: str | None = None) -> list[Source]:
        self.calls.append((query, top_k, source_type))
        return [
            Source(
                id="live-1",
                title="Live Source",
                url="https://example.com/live",
                source_type=source_type or "web",
                published_at=date(2026, 1, 1),
                content="Recorded content.",
            )
        ][:top_k]


class PartialLiveProvider(FakeLiveProvider):
    last_error_type = "TimeoutError"

    def search(self, query: str, top_k: int = 3, source_type: str | None = None) -> list[Source]:
        self.calls.append((query, top_k, source_type))
        return []


class RecordingSearchTests(unittest.TestCase):
    def test_normalized_query_key_is_stable_for_case_whitespace_and_parameter_order(self) -> None:
        left = normalize_query_key("  CATL   Profit  ", top_k=2, source_type="news")
        right = normalize_query_key("catl profit", source_type="news", top_k=2)

        self.assertEqual(left, right)

    def test_record_then_replay_returns_recorded_sources_without_live_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            recording_dir = Path(tmp) / "recordings"
            live = FakeLiveProvider()
            recorder = RecordingSearchProvider(
                mode="record",
                recording_dir=recording_dir,
                live_provider=live,
                as_of=date(2026, 6, 16),
            )

            recorded = recorder.search("CATL profit", top_k=1, source_type="news")
            recorded_again = recorder.search("CATL profit", top_k=1, source_type="news")
            replay = RecordingSearchProvider(mode="replay", recording_dir=recording_dir)
            replayed = replay.search("  catl   profit ", top_k=1, source_type="news")

        self.assertEqual(len(live.calls), 1)
        self.assertEqual(recorded[0].url, replayed[0].url)
        self.assertEqual(recorded_again[0].url, replayed[0].url)
        self.assertEqual(recorded[0].content, replayed[0].content)

    def test_record_mode_requires_explicit_as_of(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "explicit as_of"):
                RecordingSearchProvider(
                    mode="record",
                    recording_dir=Path(tmp),
                    live_provider=FakeLiveProvider(),
                )

    def test_partial_live_failure_is_recorded_for_later_backfill(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            recording_dir = Path(tmp) / "recordings"
            recorder = RecordingSearchProvider(
                mode="record",
                recording_dir=recording_dir,
                live_provider=PartialLiveProvider(),
                as_of=date(2026, 7, 8),
            )

            self.assertEqual(recorder.search("unstable query", top_k=1), [])
            path = next(recording_dir.glob("*.json"))
            payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(payload["metadata"]["status"], "partial")
        self.assertEqual(payload["metadata"]["error_type"], "TimeoutError")
        self.assertEqual(payload["metadata"]["as_of"], "2026-07-08")

    def test_replay_miss_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            replay = RecordingSearchProvider(mode="replay", recording_dir=Path(tmp))

            with self.assertRaises(RecordingReplayMiss):
                replay.search("missing query", top_k=1)

    def test_factory_replay_mode_does_not_require_live_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            provider = build_search_provider(
                {
                    "DEEPRESEARCH_SEARCH_PROVIDER": "tavily",
                    "DEEPRESEARCH_SEARCH_RECORDING_MODE": "replay",
                    "DEEPRESEARCH_SEARCH_RECORDING_DIR": tmp,
                }
            )

        self.assertIsInstance(provider, RecordingSearchProvider)

    def test_factory_record_mode_requires_settings_as_of(self) -> None:
        with self.assertRaisesRegex(ValueError, "settings.as_of"):
            build_search_provider(
                {
                    "DEEPRESEARCH_SEARCH_PROVIDER": "tavily",
                    "DEEPRESEARCH_SEARCH_RECORDING_MODE": "record",
                    "TAVILY_API_KEY": "test-key",
                }
            )

    def test_factory_record_mode_uses_settings_as_of(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            provider = build_search_provider(
                {
                    "DEEPRESEARCH_SEARCH_PROVIDER": "tavily",
                    "DEEPRESEARCH_SEARCH_RECORDING_MODE": "record",
                    "DEEPRESEARCH_SEARCH_RECORDING_DIR": tmp,
                    "TAVILY_API_KEY": "test-key",
                },
                as_of=date(2026, 7, 8),
            )

        self.assertIsInstance(provider, RecordingSearchProvider)
        self.assertEqual(provider.as_of, date(2026, 7, 8))


if __name__ == "__main__":
    unittest.main()
