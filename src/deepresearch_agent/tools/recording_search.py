from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from deepresearch_agent.schemas import Source
from deepresearch_agent.settings import project_root
from deepresearch_agent.tools.provider import SearchProvider


def normalize_query_key(query: str, top_k: int = 3, source_type: str | None = None) -> str:
    normalized_query = re.sub(r"\s+", " ", query.strip().lower())
    payload = {
        "query": normalized_query,
        "source_type": source_type or "",
        "top_k": top_k,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class RecordingMetadata:
    key: str
    query: str
    top_k: int
    source_type: str | None
    as_of: str
    recorded_at: str
    status: str = "complete"
    error_type: str | None = None


class RecordingSearchProvider:
    """Record/replay wrapper for deterministic Golden Set retrieval."""

    def __init__(
        self,
        mode: str,
        recording_dir: Path | None = None,
        live_provider: SearchProvider | None = None,
        as_of: date | None = None,
    ) -> None:
        if mode not in {"record", "replay"}:
            raise ValueError("RecordingSearchProvider mode must be record or replay.")
        if mode == "record" and live_provider is None:
            raise ValueError("record mode requires a live_provider.")
        if mode == "record" and as_of is None:
            raise ValueError("record mode requires an explicit as_of date.")
        self.mode = mode
        self.recording_dir = recording_dir or project_root() / "data" / "recordings" / "golden_v1"
        self.live_provider = live_provider
        self.as_of = as_of
        self.search_counts_toward_budget = mode == "record"
        self.recording_dir.mkdir(parents=True, exist_ok=True)
        self._frozen_sources: list[Source] | None = None

    def search(self, query: str, top_k: int = 3, source_type: str | None = None) -> list[Source]:
        key = normalize_query_key(query, top_k=top_k, source_type=source_type)
        path = self._recording_path(key)
        if self.mode == "replay":
            return self._search_frozen_corpus(query, top_k=top_k, source_type=source_type)
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            return [Source.model_validate(item) for item in payload.get("sources", [])]

        assert self.live_provider is not None
        sources = self.live_provider.search(query, top_k=top_k, source_type=source_type)
        error_type = getattr(self.live_provider, "last_error_type", None)
        metadata = RecordingMetadata(
            key=key,
            query=query,
            top_k=top_k,
            source_type=source_type,
            as_of=self.as_of.isoformat() if self.as_of else "",
            recorded_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            status="partial" if error_type else "complete",
            error_type=error_type,
        )
        payload = {
            "metadata": metadata.__dict__,
            "sources": [source.model_dump(mode="json") for source in sources],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return sources

    def _recording_path(self, key: str) -> Path:
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
        return self.recording_dir / f"{digest}.json"

    def _search_frozen_corpus(self, query: str, top_k: int, source_type: str | None) -> list[Source]:
        if top_k <= 0:
            return []
        sources = self._frozen_corpus_sources()
        candidates = self._filter_sources(sources, source_type) if source_type else sources
        if not candidates and source_type:
            candidates = sources
        scored = [
            (self._score_source(query, source), source.url, source.title, source)
            for source in candidates
        ]
        scored.sort(key=lambda item: (-item[0], item[1], item[2]))
        return [source for score, _url, _title, source in scored if score > 0][:top_k] or [
            source for _score, _url, _title, source in scored[:top_k]
        ]

    def _frozen_corpus_sources(self) -> list[Source]:
        if self._frozen_sources is not None:
            return self._frozen_sources
        by_url: dict[str, Source] = {}
        for path in sorted(self.recording_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            sources = payload.get("sources", [])
            if not sources:
                continue
            for item in sources:
                try:
                    source = Source.model_validate(item)
                except ValueError:
                    continue
                if not source.content.strip():
                    continue
                by_url.setdefault(source.url, source)
        self._frozen_sources = list(by_url.values())
        return self._frozen_sources

    def _filter_sources(self, sources: list[Source], source_type: str | None) -> list[Source]:
        if not source_type:
            return sources
        normalized = source_type.strip().lower()
        if normalized == "news":
            return [source for source in sources if source.source_type == "news"]
        return [
            source for source in sources
            if source.source_type == normalized or source.source_type == "web"
        ]

    def _score_source(self, query: str, source: Source) -> int:
        query_terms = set(self._tokens(query))
        if not query_terms:
            return 0
        title_terms = set(self._tokens(source.title))
        content_terms = set(self._tokens(source.content))
        return len(query_terms & title_terms) * 3 + len(query_terms & content_terms)

    def _tokens(self, text: str) -> list[str]:
        lowered = text.lower()
        ascii_words = re.findall(r"[a-z0-9]+", lowered)
        chinese_terms = re.findall(r"[\u4e00-\u9fff]{2,}", lowered)
        chinese_windows: list[str] = []
        for term in chinese_terms:
            chinese_windows.append(term)
            chinese_windows.extend(term[index : index + 2] for index in range(max(0, len(term) - 1)))
            chinese_windows.extend(term[index : index + 3] for index in range(max(0, len(term) - 2)))
        return ascii_words + chinese_windows


def recording_corpus_fingerprint(recording_dir: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(recording_dir.glob("*.json")):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()
