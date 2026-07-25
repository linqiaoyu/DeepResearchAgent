from __future__ import annotations

import hashlib
import html
import re
from collections.abc import Mapping
from datetime import date, datetime, timezone
from typing import Any

import httpx

from deepresearch_agent.schemas import Source
from deepresearch_agent.tools.contracts import ToolErrorKind, ToolSpec
from deepresearch_agent.tools.reliable_execution import (
    ReliableToolExecutor,
    RetryBudget,
    RunToolContext,
    ToolExecutionError,
)
from deepresearch_agent.tools.tavily_search import decode_pdf_source
from deepresearch_agent.trajectory import ToolCallTrace, active_trajectory_recorder

CNINFO_QUERY_ENDPOINT = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
CNINFO_STOCK_ENDPOINT = "https://www.cninfo.com.cn/new/data/szse_stock.json"
CNINFO_PDF_ROOT = "https://static.cninfo.com.cn/"
DISCLOSURE_TOOL_SPEC = ToolSpec(
    name="disclosure_source",
    version="1.0.0",
    input_schema={"type": "object", "required": ["security_code", "keyword", "start_date", "end_date"]},
    output_schema={"type": "array", "items": {"$ref": "Source"}},
    timeout_s=30.0,
    cost_class="free",
    idempotent=True,
    has_side_effect=False,
)


class DisclosureSourceError(ToolExecutionError):
    """Fail-closed error for the undocumented CNINFO endpoint."""


class CninfoDisclosureSource:
    """POST form: code/orgId + keyword + date range; then fetch announcement PDFs."""

    def __init__(
        self,
        *,
        client: Any | None = None,
        context: RunToolContext | None = None,
        max_results: int = 5,
        pdf_max_pages: int = 100,
        char_limit: int = 40_000,
    ) -> None:
        self.client = client or httpx.Client(headers={
            "User-Agent": "Mozilla/5.0 (compatible; DeepResearchAgent/0.1)",
            "Referer": "https://www.cninfo.com.cn/",
            "X-Requested-With": "XMLHttpRequest",
        })
        self.context = context or RunToolContext(RetryBudget(max_retries=2))
        self.max_results = max(1, min(max_results, 30))
        self.pdf_max_pages, self.char_limit = max(1, pdf_max_pages), char_limit

    def search(
        self, security_code: str, keyword: str, start_date: date, end_date: date
    ) -> list[Source]:
        inputs = {
            "security_code": security_code, "keyword": keyword,
            "start_date": start_date.isoformat(), "end_date": end_date.isoformat(),
        }
        result = ReliableToolExecutor().execute(
            DISCLOSURE_TOOL_SPEC, lambda: self._request(inputs), self.context
        )
        recorder = active_trajectory_recorder()
        if recorder:
            recorder.record_tool_call(ToolCallTrace(
                tool_spec=DISCLOSURE_TOOL_SPEC.model_dump(mode="json"),
                inputs=inputs,
                result=[item.model_dump(mode="json") for item in list(result.value or [])],
                error=result.error.model_dump(mode="json") if result.error else None,
                attempts=result.attempts,
            ))
        if not result.ok:
            assert result.error
            raise DisclosureSourceError(result.error.kind, result.error.message)
        return list(result.value or [])

    def _request(self, inputs: Mapping[str, str]) -> list[Source]:
        try:
            stock = self.client.get(
                CNINFO_STOCK_ENDPOINT, timeout=30.0, follow_redirects=True
            )
            stock.raise_for_status()
            org_id = next((
                str(item["orgId"]) for item in stock.json().get("stockList", [])
                if item.get("code") == inputs["security_code"]
            ), "")
            if not org_id:
                raise DisclosureSourceError(
                    ToolErrorKind.NOT_FOUND,
                    f"cninfo_security_not_found code={inputs['security_code']}",
                )
            response = self.client.post(CNINFO_QUERY_ENDPOINT, data={
                "pageNum": "1", "pageSize": str(self.max_results), "tabName": "fulltext",
                "column": "szse", "stock": f"{inputs['security_code']},{org_id}",
                "searchkey": inputs["keyword"], "plate": "sz", "category": "",
                "seDate": f"{inputs['start_date']}~{inputs['end_date']}", "isHLtitle": "true",
            }, timeout=30.0)
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
        except DisclosureSourceError:
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
        sources: list[Source] = []
        for item in (announcements or [])[: self.max_results]:
            if not isinstance(item, Mapping) or not item.get("adjunctUrl"):
                continue
            if str(item.get("secCode")) != inputs["security_code"]:
                raise DisclosureSourceError(
                    ToolErrorKind.PERMANENT, "cninfo_contract_changed: security filter mismatch"
                )
            url = CNINFO_PDF_ROOT + str(item["adjunctUrl"]).lstrip("/")
            pdf = self.client.get(url, timeout=30.0, follow_redirects=True)
            pdf.raise_for_status()
            title = re.sub(r"<[^>]+>", "", html.unescape(str(item.get("announcementTitle", ""))))
            published = datetime.fromtimestamp(
                int(item["announcementTime"]) / 1000, tz=timezone.utc
            ).date()
            sources.append(decode_pdf_source(
                url, bytes(pdf.content), max_pages=self.pdf_max_pages,
                char_limit=self.char_limit,
                source_id=f"cninfo-{hashlib.sha1(url.encode()).hexdigest()[:12]}",
                title=title, source_type="disclosure_pdf",
                published_at=published, source_tier="primary",
            ))
        return sources
