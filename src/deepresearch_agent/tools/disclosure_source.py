from __future__ import annotations

import hashlib
import html
import re
import threading
from collections.abc import Mapping
from datetime import date, datetime, timezone
from typing import Any

import httpx

from deepresearch_agent.schemas import Source
from deepresearch_agent.tools.contracts import (
    DegradationEvent,
    ToolError,
    ToolErrorKind,
    ToolResult,
    ToolSpec,
)
from deepresearch_agent.tools.reliable_execution import (
    ReliableToolExecutor,
    RetryBudget,
    RunToolContext,
    ToolExecutionScope,
    ToolExecutionError,
)
from deepresearch_agent.tools.tavily_search import decode_pdf_source
from deepresearch_agent.trajectory import ToolCallTrace, active_trajectory_recorder

CNINFO_QUERY_ENDPOINT = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
CNINFO_STOCK_ENDPOINT = "https://www.cninfo.com.cn/new/data/szse_stock.json"
CNINFO_PDF_ROOT = "https://static.cninfo.com.cn/"
_ORG_ID_CACHE: dict[str, str] = {}
_ORG_ID_CACHE_LOCK = threading.Lock()
DISCLOSURE_TOOL_SPEC = ToolSpec(
    name="disclosure_source",
    version="1.0.0",
    input_schema={"type": "object", "required": ["security_code", "keyword", "start_date", "end_date"]},
    output_schema={"type": "array", "items": {"$ref": "Source"}},
    # One logical attempt performs stock-list GET, announcement POST, one
    # selected annual-report GET, and local PDF decoding serially.  Individual
    # HTTP calls remain bounded at 30s; the aggregate executor timeout must not
    # spawn an overlapping retry while the first bounded attempt is still
    # running.
    timeout_s=120.0,
    # ``timeout_s`` is per attempt.  The matching total deadline prevents the
    # retry envelope from turning a documented two-minute ceiling into six
    # minutes, and prevents an overdue daemon worker from spawning a retry.
    total_timeout_s=120.0,
    cost_class="free",
    idempotent=True,
    has_side_effect=False,
)


def cninfo_exchange_for_security_code(security_code: str) -> tuple[str, str]:
    """Return CNINFO's ``column`` and ``plate`` for a mainland A-share code.

    Coverage is deliberately limited to Shanghai and Shenzhen A shares.  Beijing
    Exchange, Hong Kong, funds, bonds, and unrecognised codes are rejected
    instead of being silently searched with Shenzhen parameters.
    """
    if not re.fullmatch(r"\d{6}", security_code):
        raise ValueError("security code must be a six-digit mainland A-share code")
    if security_code.startswith(("600", "601", "603", "605", "688", "689")):
        return "sse", "sh"
    if security_code.startswith(("000", "001", "002", "003", "300", "301")):
        return "szse", "sz"
    raise ValueError(
        "unsupported exchange for disclosure source: only Shanghai and Shenzhen A shares are covered"
    )


class DisclosureSourceError(ToolExecutionError):
    """Fail-closed error for the undocumented CNINFO endpoint."""


class FixtureDisclosureSource:
    """Offline disclosure backend used only by deterministic test runs."""

    fidelity = "fixture"

    _ANNUAL_REPORT = Source(
        id="fixture-primary-catl-2024",
        title="宁德时代新能源科技股份有限公司2024年年度报告",
        url="fixture://cninfo/300750/2024-annual-report",
        source_type="disclosure_pdf",
        source_tier="primary",
        published_at=date(2025, 3, 15),
        credibility=1.0,
        content=(
            "[[PDF_PAGE=1]]\n宁德时代新能源科技股份有限公司2024年年度报告\n"
            "主要会计数据\n单位：人民币百万元\n"
            "2024年 2023年 2022年\n"
            "营业收入 362013 400917 328594 -9.70\n"
            "归属于上市公司股东的净利润 50745 44121 30729 15.01\n"
        ),
    )

    def set_run_context(self, context: RunToolContext) -> None:
        del context

    def search(
        self,
        security_code: str,
        keyword: str,
        start_date: date,
        end_date: date,
        *,
        preferred_terms: tuple[str, ...] = (),
    ) -> list[Source]:
        del start_date, end_date, preferred_terms
        if security_code == "300750" and keyword == "年度报告":
            return [self._ANNUAL_REPORT]
        return []


class CninfoDisclosureSource:
    """Fetch Shanghai/Shenzhen A-share CNINFO announcement PDFs by code and date.

    The adapter does not cover Beijing Exchange, Hong Kong listings, funds,
    bonds, or non-six-digit identifiers.  Unsupported codes fail closed before
    a network request rather than being queried as Shenzhen securities.
    """

    fidelity = "real"

    def __init__(
        self,
        *,
        client: Any | None = None,
        context: RunToolContext | None = None,
        max_results: int = 5,
        pdf_max_pages: int = 100,
        char_limit: int = 40_000,
        executor: ReliableToolExecutor | None = None,
        tool_spec: ToolSpec = DISCLOSURE_TOOL_SPEC,
    ) -> None:
        self._owns_client = client is None
        self.client = client or httpx.Client(headers={
            "User-Agent": "Mozilla/5.0 (compatible; DeepResearchAgent/0.1)",
            "Referer": "https://www.cninfo.com.cn/",
            "X-Requested-With": "XMLHttpRequest",
        })
        self.context = context or RunToolContext(RetryBudget(max_retries=2))
        self.max_results = max(1, min(max_results, 30))
        self.pdf_max_pages, self.char_limit = max(1, pdf_max_pages), char_limit
        self.executor = executor or ReliableToolExecutor()
        self.tool_spec = tool_spec
        self.last_result: ToolResult | None = None
        self._timeout_scope: ToolExecutionScope | None = None
        self._timeout_scope_lock = threading.Lock()

    def set_run_context(self, context: RunToolContext) -> None:
        self.context = context

    def close(self) -> None:
        close = getattr(self.client, "close", None)
        if callable(close):
            close()

    def __enter__(self) -> "CninfoDisclosureSource":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    @property
    def timed_out_operation_pending(self) -> bool:
        with self._timeout_scope_lock:
            scope = self._timeout_scope
            if scope is not None and scope.finished:
                self._timeout_scope = None
                return False
            return scope is not None

    @staticmethod
    def _consume_egress(
        request_kind: str,
        *,
        context: RunToolContext,
        scope: ToolExecutionScope,
    ) -> None:
        scope.raise_if_cancelled()
        context.consume_external_request(
            request_kind,
            tool="disclosure_source",
        )
        scope.raise_if_cancelled()

    def search(
        self, security_code: str, keyword: str, start_date: date, end_date: date,
        *, preferred_terms: tuple[str, ...] = (),
    ) -> list[Source]:
        # Capture the run context before starting a worker.  ``set_run_context``
        # may install the next run while an uncooperative provider call is still
        # unwinding; the detached worker must never charge or mutate that new
        # context.
        run_context = self.context
        inputs = {
            "security_code": security_code, "keyword": keyword,
            "start_date": start_date.isoformat(), "end_date": end_date.isoformat(),
        }
        rejected_before = (
            len(run_context.external_request_budget.rejected_events)
            if run_context.external_request_budget is not None
            else 0
        )
        if self.timed_out_operation_pending:
            result = self._quarantined_result(run_context)
        else:
            scope = ToolExecutionScope()
            result = self.executor.execute(
                self.tool_spec,
                lambda: self._request(
                    inputs,
                    preferred_terms=preferred_terms,
                    context=run_context,
                    scope=scope,
                ),
                run_context,
                degrade=True,
                degraded_value=[],
                impact=(
                    "primary disclosure unavailable; falling back to "
                    "lower-authority web sources"
                ),
                operation_scope=scope,
            )
            if scope.cancelled and not scope.finished:
                with self._timeout_scope_lock:
                    self._timeout_scope = scope
        self.last_result = result
        sources = list(result.value or [])
        if result.ok and not sources:
            run_context.degradation_events.append(
                DegradationEvent(
                    tool=self.tool_spec.name,
                    reason=ToolErrorKind.NOT_FOUND,
                    impact=(
                        "primary disclosure returned no matching document; "
                        "falling back to lower-authority web sources"
                    ),
                    attempts=result.attempts,
                )
            )
        degradation_event = self._result_degradation_event(
            result,
            sources,
            run_context,
        )
        recorder = active_trajectory_recorder()
        if recorder:
            recorder.record_tool_call(ToolCallTrace(
                tool_spec=self.tool_spec.model_dump(mode="json"),
                inputs=inputs,
                result=[item.model_dump(mode="json") for item in list(result.value or [])],
                error=result.error.model_dump(mode="json") if result.error else None,
                degradation_event=degradation_event,
                attempts=result.attempts,
            ))
        if not result.ok:
            assert result.error
            if self._external_budget_refused(
                result,
                rejected_before,
                run_context,
            ):
                raise DisclosureSourceError(
                    result.error.kind,
                    result.error.message,
                )
            return []
        return sources

    def _result_degradation_event(
        self,
        result: ToolResult,
        sources: list[Source],
        context: RunToolContext,
    ) -> dict[str, Any] | None:
        if not context.degradation_events:
            return None
        event = context.degradation_events[-1]
        belongs_to_result = (
            event.tool == self.tool_spec.name
            and event.attempts == result.attempts
            and (not result.ok or result.attempts > 1 or not sources)
        )
        return event.model_dump(mode="json") if belongs_to_result else None

    def _external_budget_refused(
        self,
        result: ToolResult,
        rejected_before: int,
        context: RunToolContext,
    ) -> bool:
        if not result.error or result.error.kind != ToolErrorKind.BUDGET_EXCEEDED:
            return False
        budget = context.external_request_budget
        return bool(
            budget
            and len(budget.rejected_events) > rejected_before
            and budget.rejected_events[-1].get("tool")
            == self.tool_spec.name
        )

    def _quarantined_result(
        self,
        context: RunToolContext,
    ) -> ToolResult:
        message = (
            "previous timed-out disclosure operation is still terminating; "
            "provider instance quarantined"
        )
        context.degradation_events.append(
            DegradationEvent(
                tool=self.tool_spec.name,
                reason=ToolErrorKind.TIMEOUT,
                impact=(
                    "primary disclosure unavailable; falling back to "
                    "lower-authority web sources"
                ),
                attempts=0,
            )
        )
        return ToolResult(
            ok=False,
            value=[],
            error=ToolError(
                kind=ToolErrorKind.TIMEOUT,
                message=message,
                exception_type="DetachedToolOperationError",
            ),
            attempts=0,
            elapsed_ms=0,
            degraded=True,
        )

    def _request(
        self,
        inputs: Mapping[str, str],
        *,
        preferred_terms: tuple[str, ...] = (),
        context: RunToolContext,
        scope: ToolExecutionScope,
    ) -> list[Source]:
        try:
            column, plate = cninfo_exchange_for_security_code(inputs["security_code"])
            with _ORG_ID_CACHE_LOCK:
                org_id = (
                    _ORG_ID_CACHE.get(inputs["security_code"], "")
                    if self._owns_client
                    else ""
                )
            if not org_id:
                self._consume_egress("fetch", context=context, scope=scope)
                stock = self.client.get(
                    CNINFO_STOCK_ENDPOINT, timeout=30.0, follow_redirects=True
                )
                scope.raise_if_cancelled()
                stock.raise_for_status()
                org_id = next((
                    str(item["orgId"]) for item in stock.json().get("stockList", [])
                    if item.get("code") == inputs["security_code"]
                ), "")
                if org_id and self._owns_client:
                    with _ORG_ID_CACHE_LOCK:
                        _ORG_ID_CACHE[inputs["security_code"]] = org_id
            if not org_id:
                raise DisclosureSourceError(
                    ToolErrorKind.NOT_FOUND,
                    f"cninfo_security_not_found code={inputs['security_code']}",
                )
            self._consume_egress("search", context=context, scope=scope)
            response = self.client.post(CNINFO_QUERY_ENDPOINT, data={
                "pageNum": "1", "pageSize": str(self.max_results), "tabName": "fulltext",
                "column": column, "stock": f"{inputs['security_code']},{org_id}",
                "searchkey": inputs["keyword"], "plate": plate, "category": "",
                "seDate": f"{inputs['start_date']}~{inputs['end_date']}", "isHLtitle": "true",
            }, timeout=30.0)
            scope.raise_if_cancelled()
            response.raise_for_status()
            body = response.json()
            if not isinstance(body, Mapping) or "announcements" not in body:
                raise DisclosureSourceError(
                    ToolErrorKind.PERMANENT,
                    "cninfo_contract_changed: announcements list missing",
                )
            announcements = body["announcements"]
        except httpx.TimeoutException as exc:
            raise DisclosureSourceError(ToolErrorKind.TIMEOUT, str(exc)) from exc
        except httpx.HTTPStatusError as exc:
            raise DisclosureSourceError(
                self._http_error_kind(exc),
                f"cninfo_http_status={exc.response.status_code}",
            ) from exc
        except DisclosureSourceError:
            raise
        except ToolExecutionError:
            raise
        except Exception as exc:
            raise DisclosureSourceError(
                ToolErrorKind.TRANSIENT,
                f"cninfo_query_failed error_type={type(exc).__name__}",
            ) from exc
        if not isinstance(announcements, (list, type(None))):
            raise DisclosureSourceError(
                ToolErrorKind.PERMANENT, "cninfo_contract_changed: announcements list missing"
            )
        candidates = list(announcements or [])[: self.max_results]
        if inputs["keyword"] == "年度报告":
            full_chinese_reports = [
                item
                for item in candidates
                if isinstance(item, Mapping)
                and re.search(
                    r"20\d{2}年年度报告$",
                    re.sub(
                        r"<[^>]+>",
                        "",
                        html.unescape(
                            str(item.get("announcementTitle", ""))
                        ),
                    ),
                )
            ]
            # CNINFO also returns the English report, summary, half-year report,
            # and half-year summary for this query.  A financial metric branch
            # needs the first full Chinese annual report, not five overlapping
            # documents in one LLM context.  Keep the original bounded fallback
            # when the endpoint does not expose an exact full-report title.
            if full_chinese_reports:
                candidates = full_chinese_reports[:1]
        # A single research branch needs one authoritative document.  Keeping
        # this bound for every keyword preserves the documented 120s attempt
        # ceiling and prevents overlapping PDFs from entering one context.
        candidates = candidates[:1]
        if candidates and not any(
            isinstance(item, Mapping) and item.get("adjunctUrl")
            for item in candidates
        ):
            raise DisclosureSourceError(
                ToolErrorKind.PERMANENT,
                "cninfo_contract_changed: no valid announcement entries",
            )
        sources: list[Source] = []
        for item in candidates:
            if not isinstance(item, Mapping) or not item.get("adjunctUrl"):
                continue
            if str(item.get("secCode")) != inputs["security_code"]:
                raise DisclosureSourceError(
                    ToolErrorKind.PERMANENT, "cninfo_contract_changed: security filter mismatch"
                )
            url = CNINFO_PDF_ROOT + str(item["adjunctUrl"]).lstrip("/")
            try:
                self._consume_egress(
                    "fetch", context=context, scope=scope
                )
                pdf = self.client.get(
                    url,
                    timeout=30.0,
                    follow_redirects=True,
                )
                scope.raise_if_cancelled()
                pdf.raise_for_status()
                title = re.sub(
                    r"<[^>]+>",
                    "",
                    html.unescape(
                        str(item.get("announcementTitle", ""))
                    ),
                )
                published = datetime.fromtimestamp(
                    int(item["announcementTime"]) / 1000,
                    tz=timezone.utc,
                ).date()
                sources.append(
                    decode_pdf_source(
                        url,
                        bytes(pdf.content),
                        max_pages=self.pdf_max_pages,
                        char_limit=self.char_limit,
                        source_id=(
                            "cninfo-"
                            + hashlib.sha1(
                                url.encode()
                            ).hexdigest()[:12]
                        ),
                        title=title,
                        source_type="disclosure_pdf",
                        published_at=published,
                        source_tier="primary",
                        preferred_terms=preferred_terms,
                    )
                )
            except httpx.TimeoutException as exc:
                raise DisclosureSourceError(
                    ToolErrorKind.TIMEOUT,
                    "cninfo_pdf_timeout",
                ) from exc
            except httpx.HTTPStatusError as exc:
                raise DisclosureSourceError(
                    self._http_error_kind(exc),
                    f"cninfo_pdf_http_status={exc.response.status_code}",
                ) from exc
            except ToolExecutionError:
                raise
            except Exception as exc:
                raise DisclosureSourceError(
                    ToolErrorKind.TRANSIENT,
                    f"cninfo_pdf_failed error_type={type(exc).__name__}",
                ) from exc
        return sources

    @staticmethod
    def _http_error_kind(exc: httpx.HTTPStatusError) -> ToolErrorKind:
        status = exc.response.status_code
        if status == 429:
            return ToolErrorKind.RATE_LIMITED
        if status in {401, 403}:
            return ToolErrorKind.AUTH
        if status == 404:
            return ToolErrorKind.NOT_FOUND
        if status >= 500:
            return ToolErrorKind.TRANSIENT
        return ToolErrorKind.PERMANENT
