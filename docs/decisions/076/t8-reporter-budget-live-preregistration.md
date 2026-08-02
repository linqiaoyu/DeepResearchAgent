# T8 reporter-budget live validation preregistration

Date: 2026-08-02. The user authorized one paid run (CNY 15) and a CNY 20 round
cap. Commit `570e34f` bounds reporter evidence/output after R074 completed
extraction but exhausted reporter retries. Run Alibaba 2024 20-F, as-of
2026-07-01, depth 1, `sec_companyfacts`, live LLM/search/RAG,
`data/runtime/047-assets.db`, index
`finance_v1-43f11085-heading_page_first_1024_256`. LLM/RAG/total caps are
CNY 3/12/15. Stop on provider retry exhaustion, cost breach, or delivery
failure; do not rerun. Any later paid call requires fresh authorization.
