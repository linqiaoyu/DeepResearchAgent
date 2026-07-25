from __future__ import annotations

import hashlib
import html
import io
import json
import re
import time
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx

from deepresearch_agent.schemas import Source
from deepresearch_agent.settings import project_root
from deepresearch_agent.tools.contracts import ToolErrorKind
from deepresearch_agent.tools.reliable_execution import RunToolContext, ToolExecutionError

TAVILY_SEARCH_ENDPOINT = "https://api.tavily.com/search"
UNKNOWN_PUBLISHED_AT = date(1970, 1, 1)


class TavilySearchError(RuntimeError):
    """Raised when Tavily search cannot return a provider payload."""


class PdfDecodeError(ToolExecutionError):
    """Fail-closed error for a response identified as PDF but not decodable."""

    def __init__(self, message: str) -> None:
        super().__init__(ToolErrorKind.PERMANENT, message)


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

    def get(
        self,
        url: str,
        *,
        timeout: float,
        follow_redirects: bool,
    ) -> Any:
        """Fetch a source document by URL."""


def decode_pdf_source(
    url: str,
    content: bytes,
    *,
    max_pages: int,
    char_limit: int,
    source_id: str,
    title: str | None = None,
    source_type: str = "web_fetch_pdf",
    published_at: date = UNKNOWN_PUBLISHED_AT,
    source_tier: str = "unknown",
) -> Source:
    """Decode PDF bytes through the single pypdf path used by all tools."""
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(content), strict=False)
        pages = reader.pages[: max(1, max_pages)]
        text = "\n".join(page.extract_text() or "" for page in pages)
    except Exception as exc:
        raise PdfDecodeError(
            f"pdf_decode_failed url={url} error_type={type(exc).__name__}"
        ) from exc
    if not text.strip():
        raise PdfDecodeError(f"pdf_decode_empty url={url} pages={len(reader.pages)}")
    return Source(
        id=source_id,
        title=title or urlsplit(url).path.rsplit("/", 1)[-1] or url,
        url=url,
        source_type=source_type,
        published_at=published_at,
        content=text[:char_limit],
        credibility=1.0 if source_tier == "primary" else 0.8,
        source_tier=source_tier,
        content_truncated=len(reader.pages) > max_pages or len(text) > char_limit,
    )


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
        pdf_max_pages: int = 100,
        ledger_path: Path | None = None,
        credit_warning_threshold: int = 450,
        credit_hard_threshold: int = 520,
        sleep_func: Any = time.sleep,
        context: RunToolContext | None = None,
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
        self.pdf_max_pages = max(1, pdf_max_pages)
        self.ledger_path = ledger_path or project_root() / "data" / "runtime" / "search_ledger.jsonl"
        self.credit_warning_threshold = credit_warning_threshold
        self.credit_hard_threshold = credit_hard_threshold
        self._sleep = sleep_func
        self.last_error_type: str | None = None
        self.search_counts_toward_budget = True
        self._run_context = context
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)

    def set_run_context(self, context: RunToolContext) -> None:
        self._run_context = context

    def _consume_egress(self, request_kind: str) -> None:
        if self._run_context is not None:
            self._run_context.consume_external_request(
                request_kind, tool="tavily_search"
            )

    def search(self, query: str, top_k: int = 3, source_type: str | None = None) -> list[Source]:
        if top_k <= 0:
            return []
        self.last_error_type = None

        max_results = min(top_k, 20)
        credit_estimate = 2 if self.search_depth == "advanced" else 1
        projected_credit_total = self._ledger_credit_total() + credit_estimate
        guardrail_warning = projected_credit_total >= self.credit_warning_threshold
        if projected_credit_total > self.credit_hard_threshold:
            self.last_error_type = "credit_hard_threshold"
            self._record_ledger(
                query=query,
                search_depth=self.search_depth,
                credit_estimate=0,
                latency_seconds=0.0,
                success=False,
                result_count=0,
                error_type="credit_hard_threshold",
                refused=True,
                guardrail_warning=True,
            )
            raise TavilySearchError("Tavily credit hard threshold reached; stop live recording.")

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
                self._consume_egress("search")
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
                    refused=False,
                    guardrail_warning=guardrail_warning,
                )
                return sources
            except Exception as exc:
                if isinstance(exc, ToolExecutionError) and exc.kind == ToolErrorKind.BUDGET_EXCEEDED:
                    raise
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
            refused=False,
            guardrail_warning=guardrail_warning,
        )
        self.last_error_type = type(last_error).__name__ if last_error else "unknown"
        return []

    def fetch(self, url: str) -> Source | None:
        """Hydrate a search result with the publisher's response body."""

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                self._consume_egress("fetch")
                response = self.client.get(
                    url,
                    timeout=self.timeout_seconds,
                    follow_redirects=True,
                )
                response.raise_for_status()
                if self._is_pdf_response(url, response):
                    return self._pdf_source(url, bytes(response.content))
                raw = str(response.text)
                title_match = re.search(
                    r"<title[^>]*>(.*?)</title>",
                    raw,
                    re.IGNORECASE | re.DOTALL,
                )
                title = (
                    self._html_text(title_match.group(1))
                    if title_match
                    else url
                )
                content = self._html_text(raw)[: self.raw_content_char_limit]
                if not content:
                    return None
                return Source(
                    id=self._source_id(url, title),
                    title=title or url,
                    url=url,
                    source_type="web_fetch",
                    published_at=UNKNOWN_PUBLISHED_AT,
                    content=content,
                    credibility=0.8,
                )
            except PdfDecodeError:
                self.last_error_type = "PdfDecodeError"
                raise
            except ToolExecutionError as exc:
                if exc.kind == ToolErrorKind.BUDGET_EXCEEDED:
                    raise
                last_error = exc
            except Exception as exc:
                last_error = exc
                if attempt < self.max_retries:
                    self._sleep(2**attempt)
        self.last_error_type = (
            type(last_error).__name__ if last_error else "unknown"
        )
        return None

    def _is_pdf_response(self, url: str, response: Any) -> bool:
        headers = getattr(response, "headers", {})
        content_type = str(headers.get("content-type", "")).split(";", 1)[0].lower()
        return content_type == "application/pdf" or urlsplit(url).path.lower().endswith(".pdf")

    def _pdf_source(self, url: str, content: bytes) -> Source:
        title = urlsplit(url).path.rsplit("/", 1)[-1] or url
        return decode_pdf_source(
            url,
            content,
            max_pages=self.pdf_max_pages,
            char_limit=self.raw_content_char_limit,
            source_id=self._source_id(url, title),
        )

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

    def _html_text(self, value: str) -> str:
        without_scripts = re.sub(
            r"<(?:script|style)[^>]*>.*?</(?:script|style)>",
            " ",
            value,
            flags=re.IGNORECASE | re.DOTALL,
        )
        without_tags = re.sub(r"<[^>]+>", " ", without_scripts)
        return " ".join(html.unescape(without_tags).split())

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
        refused: bool,
        guardrail_warning: bool,
    ) -> None:
        row = {
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "provider": "tavily",
            "query": query,
            "search_depth": search_depth,
            "credit_estimate": credit_estimate,
            "refused": refused,
            "guardrail_warning": guardrail_warning,
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
                row = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if row.get("refused"):
                continue
            try:
                total += int(row.get("credit_estimate", 0) or 0)
            except (TypeError, ValueError):
                continue
        return total
