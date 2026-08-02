"""Offline regression probe for full-subquestion RAG period filters."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from deepresearch_agent.domains.registry import load_domain_pack
from deepresearch_agent.rag.backends import StorageLexicalBackend
from deepresearch_agent.rag.search import RetrievalFilter
from deepresearch_agent.storage.sqlite_store import SQLiteStore


def main() -> int:
    question = "蔚来 2024 年年报的营收与毛利情况"
    queries = ["NIO Inc. 年度报告", "蔚来 2024 第四季度及全年财报 营收", "NIO 2024 annual results revenue", "蔚来 2024 年报 营业收入 同比"]
    domain_pack = load_domain_pack("finance")
    values = domain_pack.retrieval_filter_values(" ".join([question, *queries]))
    backend = StorageLexicalBackend(store=SQLiteStore(Path("data/runtime/047-assets.db")))
    candidates = backend.search(query=queries[0], filters=RetrievalFilter(period_labels=values.period_labels, as_of=date(2026, 7, 1)), limit=100)
    fallback = domain_pack.retrieval_filter_values("年度报告营收").period_labels
    off_scope = sum(chunk.effective_date.year not in {2023, 2024} for chunk in candidates)
    print(f"period_labels={','.join(values.period_labels)}")
    print(f"lexical_candidates={len(candidates)}")
    print(f"in_scope_candidates={len(candidates) - off_scope}")
    print(f"off_scope_candidates={off_scope}")
    print(f"no_year_fallback={'unfiltered' if not fallback else 'filtered'}")
    return int(not (values.period_labels == ('2023', '2024') and candidates and not off_scope and not fallback))


if __name__ == "__main__":
    raise SystemExit(main())
