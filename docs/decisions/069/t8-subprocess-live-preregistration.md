# T8 subprocess-isolated live validation preregistration

Date: 2026-08-02

The user authorized one paid attempt (CNY 15) and a CNY 20 round ceiling.
R068 changed production LiteLLM calls to spawned, killable subprocesses, so
this is a new experiment.

Frozen run: Alibaba 2024 20-F financial-performance/risk question;
`as_of=2026-07-01`; depth 1; `sec_companyfacts`; live LLM, Tavily, and RAG;
database `data/runtime/047-assets.db`; index
`finance_v1-43f11085-heading_page_first_1024_256`; `--allow-paid-api`.
LLM/RAG/total caps are CNY 3/CNY 12/CNY 15.

Acceptance: non-empty report, final manifest with requested index, at least
one RAG ledger row, manifest cost no more than CNY 15, citation-closure value
in report, and `check_real_run_manifest.py --require-active-real` passes.
Stop without retry on provider retry exhaustion, cost breaker, or delivery
failure; preserve all evidence. Any later run needs new authorization and
preregistration.
