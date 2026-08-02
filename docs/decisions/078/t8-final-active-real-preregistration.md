# T8 final active-real preregistration

User authorization: CNY 15 one run, CNY 20 round. Commit `dfd0db8` aligns the
active-real validation script with manifest semantics. Frozen Alibaba 2024 20-F
run: as-of 2026-07-01, depth 1, `sec_companyfacts`, live LLM/search/RAG,
database `data/runtime/047-assets.db`, index
`finance_v1-43f11085-heading_page_first_1024_256`. Caps: LLM/RAG/total CNY
3/12/15. Stop on retry exhaustion, breaker, or delivery failure, and do not
rerun; later paid calls require fresh authorization.
