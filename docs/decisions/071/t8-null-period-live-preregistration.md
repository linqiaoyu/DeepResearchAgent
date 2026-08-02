# T8 nullable-period live validation preregistration

Date: 2026-08-02

The user authorized one paid T8 attempt up to CNY 15 and a CNY 20 round cap.
R070's real run reached three real provider layers but failed before delivery
because `NumericFields.period=None` reached a finance helper that assumed a
string. Commit `ca2d881` makes that helper null-safe and adds a reproducing
guard. This is therefore a new experiment.

Frozen run: `阿里巴巴 2024 年 20-F 财务表现与风险因素研究`; as-of
`2026-07-01`; depth 1; structured provider `sec_companyfacts`; live LLM,
Tavily, and RAG; database `data/runtime/047-assets.db`; index
`finance_v1-43f11085-heading_page_first_1024_256`. LLM/RAG/total caps are
CNY 3/CNY 12/CNY 15.

Pass only if: output report is non-empty; final manifest says `actual_realness`
is `real`; it carries the requested index; the RAG ledger contains an embedding
or rerank row; all recorded cost is no more than CNY 15; and the report records
`audit_citation_closure`. Stop with no retry on any provider retry exhaustion,
cost breaker, provider failure, or delivery failure. Preserve all evidence. A
later paid command requires a new authorization and preregistration.
