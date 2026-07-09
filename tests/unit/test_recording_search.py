from __future__ import annotations

import tempfile
import unittest
import json
from datetime import date
from pathlib import Path

from deepresearch_agent.schemas import Source
from deepresearch_agent.tools import (
    RecordingSearchProvider,
    build_search_provider,
    normalize_query_key,
    recording_corpus_fingerprint,
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


def _write_recording(recording_dir: Path, filename: str, source: Source) -> None:
    recording_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "metadata": {
            "key": filename,
            "query": source.title,
            "top_k": 1,
            "source_type": source.source_type,
            "as_of": "2026-07-08",
            "recorded_at": "2026-07-08T00:00:00Z",
            "status": "complete",
            "error_type": None,
        },
        "sources": [source.model_dump(mode="json")],
    }
    (recording_dir / filename).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class RecordingSearchTests(unittest.TestCase):
    def test_normalized_query_key_is_stable_for_case_whitespace_and_parameter_order(self) -> None:
        left = normalize_query_key("  CATL   Profit  ", top_k=2, source_type="news")
        right = normalize_query_key("catl profit", source_type="news", top_k=2)

        self.assertEqual(left, right)

    def test_record_then_replay_searches_frozen_corpus_without_live_call(self) -> None:
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
            before_files = sorted(path.name for path in recording_dir.glob("*.json"))
            replayed = replay.search("recorded content", top_k=1, source_type="news")
            after_files = sorted(path.name for path in recording_dir.glob("*.json"))

        self.assertEqual(len(live.calls), 1)
        self.assertEqual(recorded[0].url, replayed[0].url)
        self.assertEqual(recorded_again[0].url, replayed[0].url)
        self.assertEqual(recorded[0].content, replayed[0].content)
        self.assertEqual(before_files, after_files)

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

    def test_replay_miss_path_is_retired_and_returns_empty_corpus_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            replay = RecordingSearchProvider(mode="replay", recording_dir=Path(tmp))

            self.assertEqual(replay.search("missing query", top_k=1), [])

    def test_replay_uses_source_type_filter_then_falls_back_to_all_types(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            recording_dir = Path(tmp)
            _write_recording(
                recording_dir,
                "first.json",
                Source(
                    id="news-1",
                    title="CATL profit news",
                    url="https://example.com/news",
                    source_type="news",
                    published_at=date(2026, 1, 1),
                    content="CATL profit rose in the annual report.",
                ),
            )
            _write_recording(
                recording_dir,
                "second.json",
                Source(
                    id="web-1",
                    title="BYD production report",
                    url="https://example.com/web",
                    source_type="web",
                    published_at=date(2026, 1, 1),
                    content="BYD production details.",
                ),
            )
            replay = RecordingSearchProvider(mode="replay", recording_dir=recording_dir)

            news_results = replay.search("CATL profit", top_k=2, source_type="news")
            fallback_results = replay.search("BYD production", top_k=1, source_type="company_report")

        self.assertEqual([item.url for item in news_results], ["https://example.com/news"])
        self.assertEqual([item.url for item in fallback_results], ["https://example.com/web"])

    def test_recording_corpus_fingerprint_changes_with_directory_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            recording_dir = Path(tmp)
            before = recording_corpus_fingerprint(recording_dir)
            _write_recording(
                recording_dir,
                "source.json",
                Source(
                    id="source-1",
                    title="Source title",
                    url="https://example.com/source",
                    source_type="web",
                    published_at=date(2026, 1, 1),
                    content="Source content.",
                ),
            )
            after = recording_corpus_fingerprint(recording_dir)

        self.assertNotEqual(before, after)

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
