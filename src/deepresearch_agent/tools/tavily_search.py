from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any, Protocol

import httpx

from deepresearch_agent.schemas import Source

TAVILY_SEARCH_ENDPOINT = "https://api.tavily.com/search"
UNKNOWN_PUBLISHED_AT = date(1970, 1, 1)


class HttpResponse(Protocol):
    def raise_for_status(self) -> None:
        """Raise when the provider returned a non-2xx response."""

    def json(self) -> Mapping[str, Any]:
        """Return the decoded provider payload."""


class SyncHttpClient(Protocol):
    def post(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        json: Mapping[str, Any],
        timeout: float,
    ) -> HttpResponse:
        """Post a JSON request to the provider."""


class TavilySearchProvider:
    """Tavily-backed search adapter behind the SearchProvider contract."""

    def __init__(
        self,
        api_key: str,
        client: SyncHttpClient | None = None,
        endpoint: str = TAVILY_SEARCH_ENDPOINT,
        timeout_seconds: float = 10.0,
    ) -> None:
        api_key = api_key.strip()
        if not api_key:
            raise ValueError("TavilySearchProvider requires a non-empty api_key.")
        self.api_key = api_key
        self.client = client or httpx.Client()
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds

    def search(self, query: str, top_k: int = 3, source_type: str | None = None) -> list[Source]:
        if top_k <= 0:
            return []

        max_results = min(top_k, 20)
        payload: dict[str, Any] = {
            "query": query,
            "max_results": max_results,
            "search_depth": "basic",
            "topic": self._topic_for_source_type(source_type),
            "include_answer": False,
            "include_raw_content": False,
            "include_images": False,
        }
        response = self.client.post(
            self.endpoint,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=payload,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return self._sources_from_response(response.json(), source_type)[:top_k]

    def _sources_from_response(
        self,
        payload: Mapping[str, Any],
        source_type: str | None,
    ) -> list[Source]:
        results = payload.get("results", [])
        if not isinstance(results, list):
            return []

        sources: list[Source] = []
        for result in results:
            if not isinstance(result, Mapping):
                continue
            source = self._source_from_result(result, source_type)
            if source:
                sources.append(source)
        return sources

    def _source_from_result(
        self,
        result: Mapping[str, Any],
        source_type: str | None,
    ) -> Source | None:
        url = self._text(result.get("url"))
        if not url:
            return None

        title = self._text(result.get("title")) or url
        content = self._content(result, title)
        return Source(
            id=self._source_id(url, title),
            title=title,
            url=url,
            source_type=self._source_type_for_result(source_type),
            published_at=self._published_at(result.get("published_date")),
            content=content,
            credibility=self._credibility(result.get("score")),
        )

    def _topic_for_source_type(self, source_type: str | None) -> str:
        return "news" if source_type == "news" else "general"

    def _source_type_for_result(self, source_type: str | None) -> str:
        return "news" if source_type == "news" else "web"

    def _content(self, result: Mapping[str, Any], title: str) -> str:
        raw_content = self._text(result.get("raw_content"))
        content = raw_content or self._text(result.get("content"))
        return content or title

    def _published_at(self, value: Any) -> date:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            try:
                return date.fromisoformat(value[:10])
            except ValueError:
                return UNKNOWN_PUBLISHED_AT
        return UNKNOWN_PUBLISHED_AT

    def _credibility(self, value: Any) -> float:
        try:
            score = float(value)
        except (TypeError, ValueError):
            return 0.75
        return max(0.0, min(1.0, round(score, 3)))

    def _source_id(self, url: str, title: str) -> str:
        digest = hashlib.sha1(f"{url}|{title}".encode("utf-8")).hexdigest()[:12]
        return f"tavily-{digest}"

    def _text(self, value: Any) -> str:
        return value.strip() if isinstance(value, str) else ""
