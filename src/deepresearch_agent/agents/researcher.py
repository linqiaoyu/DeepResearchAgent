from __future__ import annotations

import hashlib
import re
import inspect
import time
from datetime import date
from decimal import Decimal
from typing import Any

from deepresearch_agent.schemas import (
    AgentDecision,
    Evidence,
    NumericFields,
    SearchRecord,
    Source,
    StructuredDataRecord,
    StructuredDataRequest,
    SubQuestion,
)
from deepresearch_agent.domains.protocols import DisclosureQueryDomain
from deepresearch_agent.domains.requirements import resolve_domain_capability
from deepresearch_agent.orchestration.contracts import RunScope, SearchQuota
from deepresearch_agent.tools import (
    FetchProvider,
    FixtureSearchTool,
    FixtureStructuredDataProvider,
    SearchProvider,
    StructuredDataProvider,
    ToolErrorKind,
    ToolExecutionError,
    RunToolContext,
)
from deepresearch_agent.tools.source_ranking import (
    rerank_sources,
    source_rerank_decision,
)


def _accepts_keyword(callable_: Any, keyword: str) -> bool:
    """Allow legacy test/replay disclosure adapters during protocol migration."""
    parameters = inspect.signature(callable_).parameters.values()
    return any(
        parameter.name == keyword
        or parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters
    )


class ResearcherAgent:
    def __init__(
        self,
        search_tool: SearchProvider | None = None,
        structured_data_provider: StructuredDataProvider | None = None,
        max_searches_per_run: int = 20,
        fetch_tool: FetchProvider | None = None,
        disclosure_source: object | None = None,
        as_of: date | None = None,
        domain_pack: DisclosureQueryDomain | None = None,
    ) -> None:
        self.search_tool = search_tool or FixtureSearchTool()
        self.fetch_tool = fetch_tool or self.search_tool
        self.structured_data_provider = structured_data_provider or FixtureStructuredDataProvider()
        self.max_searches_per_run = max_searches_per_run
        self.disclosure_source = disclosure_source
        self.as_of = as_of or date.today()
        self.domain_pack = resolve_domain_capability(
            domain_pack, consumer="ResearcherAgent"
        )

    def research(
        self,
        sub_question: SubQuestion,
        top_k_per_query: int = 1,
        run_scope: RunScope | None = None,
    ) -> tuple[list[Source], list[SearchRecord]]:
        sources, records, _, _, _ = self.research_with_budget(
            sub_question,
            top_k_per_query=top_k_per_query,
            max_search_calls=None,
            run_scope=run_scope,
        )
        return sources, records

    def research_with_budget(
        self,
        sub_question: SubQuestion,
        *,
        top_k_per_query: int = 1,
        max_search_calls: int | None,
        priority_urls: list[str] | None = None,
        enable_web_search: bool = True,
        enable_web_fetch: bool = False,
        source_decision_enabled: bool = False,
        enable_disclosure: bool = False,
        run_scope: RunScope | None = None,
    ) -> tuple[list[Source], list[SearchRecord], int, bool, list[AgentDecision]]:
        run_scope = run_scope or RunScope(
            RunToolContext.for_run(), SearchQuota(self.max_searches_per_run)
        )
        seen: dict[str, Source] = {}
        records: list[SearchRecord] = []
        original_candidates: list[Source] = []
        ranked_candidates: list[Source] = []
        fetched_urls: list[str] = []
        branch_calls = 0
        branch_exhausted = False
        primary_hydrated = False
        authority_returned = False

        def consume_call() -> bool:
            nonlocal branch_calls, branch_exhausted
            if (
                max_search_calls is not None
                and branch_calls >= max_search_calls
            ):
                branch_exhausted = True
                return False
            if not self._consume_search_budget_if_needed(run_scope):
                return False
            branch_calls += 1
            return True

        if enable_disclosure and self.disclosure_source is not None:
            joined = " ".join(
                [sub_question.question, *sub_question.search_queries]
            )
            code_match = re.search(
                r"(?:股票|证券)?代码\s*[:：]?\s*(\d{6})(?!\d)|[（(](\d{6})[）)]",
                joined,
            )
            # A disclosure request must name an unambiguous security.  Do not
            # invent a company-specific fallback code from question text. A
            # typed structured request is an equally explicit identifier and
            # takes precedence over prose formatting.
            code = next(
                (
                    request.symbol
                    for request in sub_question.structured_data_requests
                    if request.symbol and re.fullmatch(r"\d{6}", request.symbol)
                ),
                "",
            )
            if not code and code_match:
                code = next(group for group in code_match.groups() if group)
            financial_intent = any(
                request.capability == "financial_indicators"
                for request in sub_question.structured_data_requests
            )
            report_years = {
                int(period[:4])
                for request in sub_question.structured_data_requests
                if request.capability == "financial_indicators"
                for period in request.periods
                if re.fullmatch(r"20\d{2}(?:1231)?", period)
            }
            # A disclosure title must match one requested financial year.  A
            # mixed-period branch has no single authoritative annual report,
            # so leave selection to the explicit structured-data requests.
            report_year = (
                next(iter(report_years)) if len(report_years) == 1 else None
            )
            keyword = self.domain_pack.primary_source_keyword(
                financial_intent=financial_intent
            )
            if code and consume_call():
                disclosure_started = time.perf_counter()
                disclosure_kwargs: dict[str, Any] = {
                    "preferred_terms": self.domain_pack.primary_source_terms(
                        financial_intent=financial_intent
                    ),
                    "context": run_scope.tool_context,
                }
                if report_year is not None and _accepts_keyword(
                    self.disclosure_source.search, "report_year"
                ):
                    disclosure_kwargs["report_year"] = report_year
                disclosed = self.disclosure_source.search(
                    code, keyword, date(2000, 1, 1), self.as_of, **disclosure_kwargs
                )
                records.append(
                    SearchRecord(
                        query=f"[disclosure] {code} {keyword}",
                        source_ids=[item.id for item in disclosed],
                        latency_ms=int(
                            (time.perf_counter() - disclosure_started) * 1000
                        ),
                    )
                )
                for source in disclosed:
                    seen[source.url] = source
                authority_returned = bool(disclosed)
                if financial_intent and authority_returned:
                    primary_hydrated = True

        # Prior URLs are re-check targets, never the entire retrieval plan.
        # When a branch ceiling exists, at least one call is reserved for an
        # independent query to avoid confirmation bias.
        priority_call_limit = (
            max(0, max_search_calls - 1)
            if max_search_calls is not None and sub_question.search_queries
            else max_search_calls
        )
        for url in priority_urls or []:
            if (
                priority_call_limit is not None
                and branch_calls >= priority_call_limit
            ):
                break
            if not consume_call():
                break
            source = self.fetch_tool.fetch(url, context=run_scope.tool_context)
            records.append(
                SearchRecord(
                    query=f"[priority_url] {url}",
                    source_ids=[source.id] if source else [],
                )
            )
            if source:
                classified = rerank_sources([source])[0]
                seen[classified.url] = classified
                original_candidates.append(classified)
                ranked_candidates.append(classified)
                fetched_urls.append(classified.url)

        for idx, query in enumerate(
            sub_question.search_queries if enable_web_search else []
        ):
            # A successfully hydrated disclosure makes additional fetches
            # redundant, but it must not silently suppress the explicitly
            # selected independent search provider.  Keep the first query for
            # cross-source evidence and stop before any further queries.
            if primary_hydrated and idx > 0:
                break
            if not consume_call():
                marker = (
                    "branch_budget_exceeded"
                    if branch_exhausted
                    else "search_limit_exceeded"
                )
                records.append(
                    SearchRecord(
                        query=f"[{marker}] {query}",
                        source_ids=[],
                    )
                )
                break
            started = time.perf_counter()
            source_type = None
            if sub_question.expected_source_types:
                source_type = sub_question.expected_source_types[idx % len(sub_question.expected_source_types)]
            requested_top_k = max(top_k_per_query, 3) if enable_web_fetch else top_k_per_query
            try:
                results = self.search_tool.search(
                    query,
                    top_k=requested_top_k,
                    source_type=source_type,
                    context=run_scope.tool_context,
                )
                if not results and source_type and consume_call():
                    results = self.search_tool.search(
                        query,
                        top_k=requested_top_k,
                        context=run_scope.tool_context,
                    )
            except ToolExecutionError as exc:
                if exc.kind != ToolErrorKind.BUDGET_EXCEEDED:
                    raise
                if not authority_returned:
                    raise
                branch_exhausted = True
                records.append(
                    SearchRecord(
                        query=f"[external_search_budget_exceeded] {query}",
                        source_ids=[],
                    )
                )
                break
            latency_ms = int((time.perf_counter() - started) * 1000)
            records.append(SearchRecord(query=query, source_ids=[source.id for source in results], latency_ms=latency_ms))
            ranking_enabled = enable_web_fetch or source_decision_enabled
            ranked = rerank_sources(results) if ranking_enabled else results
            if ranking_enabled:
                original_candidates.extend(
                    source
                    for source in results
                    if source.url not in {item.url for item in original_candidates}
                )
                ranked_candidates.extend(
                    source
                    for source in ranked
                    if source.url not in {item.url for item in ranked_candidates}
                )
            for source in ranked:
                seen[source.url] = source
                if not enable_web_fetch or primary_hydrated:
                    continue
                if not consume_call():
                    records.append(
                        SearchRecord(
                            query=f"[fetch_budget_exceeded] {source.url}",
                            source_ids=[],
                        )
                    )
                    break
                try:
                    fetched = self.fetch_tool.fetch(source.url, context=run_scope.tool_context)
                except ToolExecutionError as exc:
                    if exc.kind != ToolErrorKind.BUDGET_EXCEEDED:
                        raise
                    if not authority_returned:
                        raise
                    branch_exhausted = True
                    records.append(
                        SearchRecord(
                            query=(
                                "[external_fetch_budget_exceeded] "
                                f"{source.url}"
                            ),
                            source_ids=[],
                        )
                    )
                    break
                fetched_urls.append(source.url)
                records.append(
                    SearchRecord(
                        query=f"[web_fetch] {source.url}",
                        source_ids=[fetched.id] if fetched else [],
                    )
                )
                if fetched:
                    fetched = fetched.model_copy(
                        update={"source_tier": source.source_tier}
                    )
                    seen[fetched.url] = fetched
                    if fetched.source_tier == "primary":
                        primary_hydrated = True
                        break
            if branch_exhausted:
                break
        decisions = (
            [
                source_rerank_decision(
                    sub_question,
                    original_candidates,
                    ranked_candidates,
                    fetched_urls,
                    fetch_enabled=enable_web_fetch,
                )
            ]
            if enable_web_fetch or source_decision_enabled
            else []
        )
        return list(seen.values()), records, branch_calls, branch_exhausted, decisions

    def retry(self, query: str, source_type: str | None = None, top_k: int = 2, *, run_scope: RunScope | None = None) -> tuple[list[Source], SearchRecord]:
        run_scope = run_scope or RunScope(RunToolContext.for_run(), SearchQuota(self.max_searches_per_run))
        if not self._consume_search_budget_if_needed(run_scope):
            return [], SearchRecord(query=f"[search_limit_exceeded] {query}", source_ids=[])
        started = time.perf_counter()
        results = self.search_tool.search(query, top_k=top_k, source_type=source_type, context=run_scope.tool_context)
        if not results and source_type and self._consume_search_budget_if_needed(run_scope):
            results = self.search_tool.search(query, top_k=top_k, context=run_scope.tool_context)
        latency_ms = int((time.perf_counter() - started) * 1000)
        return results, SearchRecord(query=query, source_ids=[source.id for source in results], latency_ms=latency_ms)

    def structured_evidence(
        self, research_id: str, sub_question: SubQuestion
    ) -> tuple[list[Evidence], dict[str, object], list[dict[str, object]]]:
        evidence: list[Evidence] = []
        stats = {
            "requests": len(sub_question.structured_data_requests),
            "executed_requests": 0,
            "records": 0,
            "symbol_resolution_failures": 0,
            "execution_failures": 0,
        }
        failures: list[dict[str, object]] = []

        def record_failure(
            request: StructuredDataRequest,
            *,
            error_type: str,
            message: str,
            symbol_resolution: bool = False,
            reason: str = "structured_data_execution_failure",
            symbol: str | None = None,
        ) -> None:
            key = (
                "symbol_resolution_failures"
                if symbol_resolution
                else "execution_failures"
            )
            stats[key] += 1
            stats[f"failure_type_{error_type}"] = int(
                stats.get(f"failure_type_{error_type}", 0)
            ) + 1
            failures.append(
                {
                    "reason": reason,
                    "capability": request.capability,
                    "symbol": symbol or request.symbol,
                    "periods": list(request.periods),
                    "metrics": list(request.metrics),
                    "error_type": error_type,
                    "message": message[:500],
                }
            )

        symbol_resolutions: list[dict[str, object]] = []
        for request in sub_question.structured_data_requests:
            try:
                stats["executed_requests"] += 1
                records: list[StructuredDataRecord] = []
                if request.capability == "symbol_resolve":
                    symbol = self.structured_data_provider.symbol_resolve(request.company_name or "")
                    if symbol is None:
                        record_failure(
                            request,
                            error_type="SymbolResolutionError",
                            message="symbol_resolve returned no symbol",
                            symbol_resolution=True,
                        )
                        continue
                    symbol_resolutions.append(symbol.model_dump(mode="json"))
                    continue
                elif request.capability == "financial_indicators":
                    symbol = request.symbol or self._resolve_symbol(request.company_name)
                    if not symbol:
                        record_failure(
                            request,
                            error_type="SymbolResolutionError",
                            message="financial_indicators requires a resolvable symbol",
                            symbol_resolution=True,
                        )
                        continue
                    records = self.structured_data_provider.financial_indicators(
                        symbol,
                        periods=request.periods or None,
                        metrics=request.metrics or None,
                    )
                elif request.capability == "price_history":
                    symbol = request.symbol or self._resolve_symbol(request.company_name)
                    if not symbol:
                        record_failure(
                            request,
                            error_type="SymbolResolutionError",
                            message="price_history requires a resolvable symbol",
                            symbol_resolution=True,
                        )
                        continue
                    if not request.start_date or not request.end_date:
                        record_failure(
                            request,
                            error_type="RequestValidationError",
                            message="price_history requires start_date and end_date",
                        )
                        continue
                    records = self.structured_data_provider.price_history(
                        symbol,
                        request.start_date,
                        request.end_date,
                    )
                else:
                    record_failure(
                        request,
                        error_type="UnsupportedCapabilityError",
                        message=f"unsupported structured capability: {request.capability}",
                    )
                    continue
                for record in records:
                    evidence.append(self._evidence_from_record(research_id, sub_question.id, record))
                stats["records"] += len(records)
                if not records:
                    record_failure(
                        request,
                        error_type="StructuredDataEmptyResult",
                        message="structured data request returned no records",
                        reason="structured_data_empty_result",
                        symbol=symbol,
                    )
            except Exception as exc:
                record_failure(
                    request,
                    error_type=type(exc).__name__,
                    message=str(exc),
                )
        if failures:
            stats["failures"] = failures
        return evidence, stats, symbol_resolutions

    def _resolve_symbol(self, company_name: str | None) -> str | None:
        if not company_name:
            return None
        symbol = self.structured_data_provider.symbol_resolve(company_name)
        return symbol.symbol if symbol else None

    def _consume_search_budget_if_needed(self, run_scope: RunScope) -> bool:
        if not getattr(self.search_tool, "search_counts_toward_budget", False):
            return True
        return run_scope.search_quota.consume()

    def _evidence_from_record(
        self,
        research_id: str,
        sub_question_id: str,
        record: StructuredDataRecord,
    ) -> Evidence:
        rendered_value = format(
            Decimal(str(record.value)),
            "f",
        )
        extract_text = (
            f"{record.entity}|{record.metric_name}|{record.period}|{record.dimension}|"
            f"{rendered_value}|{record.unit}"
        )
        claim = (
            f"{record.entity} {record.period} {record.dimension}{record.metric_name}为"
            f"{rendered_value}{record.unit}。"
        )
        source_url = (
            f"akshare://{record.metric_name}/{record.symbol}/{record.period}/"
            f"{hashlib.sha1(extract_text.encode('utf-8')).hexdigest()[:10]}"
        )
        evidence_id = f"structured-{hashlib.sha1(source_url.encode('utf-8')).hexdigest()[:16]}"
        return Evidence(
            id=evidence_id,
            research_id=research_id,
            sub_question_id=sub_question_id,
            claim=claim,
            claim_type="data",
            source_kind="structured",
            source_url=source_url,
            source_title=f"{record.data_source} {record.symbol} {record.metric_name}",
            source_pub_date=record.as_of,
            extract_text=extract_text,
            confidence=0.98,
            structured_record=record,
            numeric_fields=NumericFields(
                entity=record.entity,
                metric_name=record.metric_name,
                period=record.period,
                dimension=record.dimension,
                value=record.value,
                unit=record.unit,
            ),
        )
