from __future__ import annotations

import json
import re
from pathlib import Path

from deepresearch_agent.schemas import Source
from deepresearch_agent.settings import project_root


TOKEN_RE = re.compile(r"[a-zA-Z0-9]+|[\u4e00-\u9fff]{2,}")


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in TOKEN_RE.findall(text)}


class FixtureSearchTool:
    """Deterministic local search used by the MVP and tests.

    The real implementation can swap this class for Tavily/Serper without
    changing planner/researcher/extractor contracts.
    """

    def __init__(self, source_path: Path | None = None) -> None:
        self.source_path = source_path or project_root() / "data" / "mock_data" / "sources.json"
        self._sources = self._load_sources()

    def _load_sources(self) -> list[Source]:
        raw = json.loads(self.source_path.read_text(encoding="utf-8"))
        return [Source.model_validate(item) for item in raw]

    def search(self, query: str, top_k: int = 3, source_type: str | None = None) -> list[Source]:
        query_tokens = _tokens(query)
        scored: list[tuple[float, Source]] = []
        for source in self._sources:
            if source_type and source.source_type != source_type:
                continue
            haystack = _tokens(f"{source.title} {source.content} {source.source_type}")
            overlap = len(query_tokens & haystack)
            score = overlap + source.credibility
            if overlap or not query_tokens:
                scored.append((score, source))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [source for _, source in scored[:top_k]]

    def fetch(self, url: str) -> Source | None:
        for source in self._sources:
            if source.url == url:
                return source
        return None

