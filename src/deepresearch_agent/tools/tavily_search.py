from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any, Protocol

import httpx

from deepresearch_agent.schemas import Source
from deepresearch_agent.settings import project_root

TAVILY_SEARCH_ENDPOINT = "https://api.tavily.com/search"
UNKNOWN_PUBLISHED_AT = date(1970, 1, 1)


class TavilySearchError(RuntimeError):
    """Raised when Tavily search cannot return a provider payload."""


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
        timeout_seconds: float = 60.0,
        max_retries: int = 2,
        search_depth: str = "basic",
        include_raw_content: bool = False,
        raw_content_char_limit: int = 40_000,
        ledger_path: Path | None = None,
        credit_warning_threshold: int = 450,
        sleep_func: Any = time.sleep,
    ) -> None:
        api_key = api_key.strip()
        if not api_key:
            raise ValueError("TavilySearchProvider requires a non-empty api_key.")
        self.api_key = api_key
        self.client = client or httpx.Client()
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.search_depth = search_depth
        self.include_raw_content = include_raw_content
        self.raw_content_char_limit = raw_content_char_limit
        self.ledger_path = ledger_path or project_root() / "data" / "runtime" / "search_ledger.jsonl"
        self.credit_warning_threshold = credit_warning_threshold
        self._sleep = sleep_func
        self.last_error_type: str | None = None
        self.search_counts_toward_budget = True
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)

    def search(self, query: str, top_k: int = 3, source_type: str | None = None) -> list[Source]:
        if top_k <= 0:
            return []
        self.last_error_type = None

        max_results = min(top_k, 20)
        credit_estimate = 2 if self.search_depth == "advanced" else 1
        if self._ledger_credit_total() + credit_estimate >= self.credit_warning_threshold:
            self._record_ledger(
                query=query,
                search_depth=self.search_depth,
                credit_estimate=credit_estimate,
                latency_seconds=0.0,
                success=False,
                result_count=0,
                error_type="credit_warning_threshold",
            )
            raise TavilySearchError("Tavily credit warning threshold reached; stop live recording.")

        payload: dict[str, Any] = {
            "query": query,
            "max_results": max_results,
            "search_depth": self.search_depth,
            "topic": self._topic_for_source_type(source_type),
            "include_answer": False,
            "include_raw_content": self.include_raw_content,
            "include_images": False,
        }
        last_error: Exception | None = None
        started = time.perf_counter()
        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.post(
                    self.endpoint,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                    timeout=self.timeout_seconds,
                )
                response.raise_for_status()
                response_payload = response.json()
                if not isinstance(response_payload, Mapping):
                    raise ValueError("response JSON must be an object")
                sources = self._sources_from_response(response_payload, source_type)[:top_k]
                self.last_error_type = None
                self._record_ledger(
                    query=query,
                    search_depth=self.search_depth,
                    credit_estimate=credit_estimate,
                    latency_seconds=time.perf_counter() - started,
                    success=True,
                    result_count=len(sources),
                    error_type=None,
                )
                return sources
            except Exception as exc:
                last_error = exc
                if attempt < self.max_retries:
                    self._sleep(2**attempt)

        self._record_ledger(
            query=query,
            search_depth=self.search_depth,
            credit_estimate=credit_estimate,
            latency_seconds=time.perf_counter() - started,
            success=False,
            result_count=0,
            error_type=type(last_error).__name__ if last_error else "unknown",
        )
        self.last_error_type = type(last_error).__name__ if last_error else "unknown"
        return []

    def _search_error(self, query: str, error: Exception) -> TavilySearchError:
        query_label = query.strip()[:80] or "<empty>"
        return TavilySearchError(f"Tavily search failed for query {query_label!r}: {error}")

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
        if raw_content:
            raw_content = raw_content[: self.raw_content_char_limit]
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

    def _record_ledger(
        self,
        *,
        query: str,
        search_depth: str,
        credit_estimate: int,
        latency_seconds: float,
        success: bool,
        result_count: int,
        error_type: str | None,
    ) -> None:
        row = {
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "provider": "tavily",
            "query": query,
            "search_depth": search_depth,
            "credit_estimate": credit_estimate,
            "latency_seconds": round(latency_seconds, 3),
            "success": success,
            "result_count": result_count,
            "error_type": error_type,
        }
        with self.ledger_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _ledger_credit_total(self) -> int:
        if not self.ledger_path.exists():
            return 0
        total = 0
        for line in self.ledger_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                total += int(json.loads(line).get("credit_estimate", 0) or 0)
            except (json.JSONDecodeError, ValueError):
                continue
        return total
