from __future__ import annotations

import time

from deepresearch_agent.schemas import SearchRecord, Source, SubQuestion
from deepresearch_agent.tools import FixtureSearchTool


class ResearcherAgent:
    def __init__(self, search_tool: FixtureSearchTool | None = None) -> None:
        self.search_tool = search_tool or FixtureSearchTool()

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
