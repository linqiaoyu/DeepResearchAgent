from __future__ import annotations

import tempfile
import unittest
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
            replay = RecordingSearchProvider(mode="replay", recording_dir=recording_dir)
            replayed = replay.search("  catl   profit ", top_k=1, source_type="news")

        self.assertEqual(len(live.calls), 1)
        self.assertEqual(recorded[0].url, replayed[0].url)
        self.assertEqual(recorded[0].content, replayed[0].content)

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


if __name__ == "__main__":
    unittest.main()
