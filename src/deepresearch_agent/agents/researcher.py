from __future__ import annotations

import hashlib
import time

from deepresearch_agent.schemas import Evidence, SearchRecord, Source, StructuredDataRecord, SubQuestion
from deepresearch_agent.tools import FixtureSearchTool, FixtureStructuredDataProvider, SearchProvider, StructuredDataProvider


class ResearcherAgent:
    def __init__(
        self,
        search_tool: SearchProvider | None = None,
        structured_data_provider: StructuredDataProvider | None = None,
    ) -> None:
        self.search_tool = search_tool or FixtureSearchTool()
        self.structured_data_provider = structured_data_provider or FixtureStructuredDataProvider()
        self.last_structured_stats: dict[str, int] = {}

    def research(self, sub_question: SubQuestion, top_k_per_query: int = 1) -> tuple[list[Source], list[SearchRecord]]:
        seen: dict[str, Source] = {}
        records: list[SearchRecord] = []
        for idx, query in enumerate(sub_question.search_queries):
            started = time.perf_counter()
            source_type = None
            if sub_question.expected_source_types:
                source_type = sub_question.expected_source_types[idx % len(sub_question.expected_source_types)]
            results = self.search_tool.search(query, top_k=top_k_per_query, source_type=source_type)
            if not results and source_type:
                results = self.search_tool.search(query, top_k=top_k_per_query)
            latency_ms = int((time.perf_counter() - started) * 1000)
            records.append(SearchRecord(query=query, source_ids=[source.id for source in results], latency_ms=latency_ms))
            for source in results:
                seen[source.url] = source
        return list(seen.values()), records

    def retry(self, query: str, source_type: str | None = None, top_k: int = 2) -> tuple[list[Source], SearchRecord]:
        started = time.perf_counter()
        results = self.search_tool.search(query, top_k=top_k, source_type=source_type)
        if not results and source_type:
            results = self.search_tool.search(query, top_k=top_k)
        latency_ms = int((time.perf_counter() - started) * 1000)
        return results, SearchRecord(query=query, source_ids=[source.id for source in results], latency_ms=latency_ms)

    def structured_evidence(self, research_id: str, sub_question: SubQuestion) -> list[Evidence]:
        evidence: list[Evidence] = []
        stats = {
            "requests": len(sub_question.structured_data_requests),
            "records": 0,
            "symbol_resolution_failures": 0,
            "execution_failures": 0,
        }
        for request in sub_question.structured_data_requests:
            try:
                records: list[StructuredDataRecord] = []
                if request.capability == "symbol_resolve":
                    symbol = self.structured_data_provider.symbol_resolve(request.company_name or "")
                    if symbol is None:
                        stats["symbol_resolution_failures"] += 1
                        continue
                    records = [
                        StructuredDataRecord(
                            entity=symbol.entity,
                            symbol=symbol.symbol,
                            metric_name="证券代码",
                            period=symbol.as_of.isoformat(),
                            dimension=symbol.exchange,
                            value=float(symbol.symbol),
                            unit="代码",
                            data_source=symbol.data_source,
                            as_of=symbol.as_of,
                        )
                    ]
                elif request.capability == "financial_indicators":
                    symbol = request.symbol or self._resolve_symbol(request.company_name)
                    if not symbol:
                        stats["symbol_resolution_failures"] += 1
                        continue
                    records = self.structured_data_provider.financial_indicators(
                        symbol,
                        periods=request.periods or None,
                        metrics=request.metrics or None,
                    )
                elif request.capability == "price_history":
                    symbol = request.symbol or self._resolve_symbol(request.company_name)
                    if not symbol:
                        stats["symbol_resolution_failures"] += 1
                        continue
                    if not request.start_date or not request.end_date:
                        stats["execution_failures"] += 1
                        continue
                    records = self.structured_data_provider.price_history(
                        symbol,
                        request.start_date,
                        request.end_date,
                    )
                else:
                    stats["execution_failures"] += 1
                    continue
                for record in records:
                    evidence.append(self._evidence_from_record(research_id, sub_question.id, record))
                stats["records"] += len(records)
            except Exception:
                stats["execution_failures"] += 1
        self.last_structured_stats = stats
        return evidence

    def _resolve_symbol(self, company_name: str | None) -> str | None:
        if not company_name:
            return None
        symbol = self.structured_data_provider.symbol_resolve(company_name)
        return symbol.symbol if symbol else None

    def _evidence_from_record(
        self,
        research_id: str,
        sub_question_id: str,
        record: StructuredDataRecord,
    ) -> Evidence:
        extract_text = (
            f"{record.entity}|{record.metric_name}|{record.period}|{record.dimension}|"
            f"{record.value}|{record.unit}"
        )
        claim = (
            f"{record.entity} {record.period} {record.dimension}{record.metric_name}为"
            f"{record.value:g}{record.unit}。"
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
        )
