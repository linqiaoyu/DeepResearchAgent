# T8 active-provider live validation preregistration

Date: 2026-08-02
Commit: recorded by the commit that introduces this file.

## Authorization

The user authorized exactly one T8 live attempt with a CNY 15 per-attempt
circuit breaker and a CNY 20 whole-round circuit breaker. This registration
governs one provider invocation after zero-cost preflight succeeds.

## Frozen configuration

- Topic: `阿里巴巴 2024 年 20-F 财务表现与风险因素研究`
- `as_of`: `2026-07-01`; depth 1
- RAG database: `data/runtime/047-assets.db`
- Index version: `finance_v1-43f11085-heading_page_first_1024_256`
- Mode: `live` with `--allow-paid-api`
- Workflow and RAG hard budgets: CNY 3 and CNY 12 respectively.

## Amended acceptance

The manifest is assessed with `--require-active-real`: LLM, search and RAG
must each be used and real. Disclosure and structured data may be unused only
when explicitly recorded as unused; if used, each must be real. Raw manifest
`actual_realness` remains unchanged and is expected to be `mixed` when an
optional provider is unused.

The run must also write a non-empty report containing the audit citation
closure, preserve the stated index version, and have at least one RAG embedding
or rerank ledger row. All observations will be recorded without tuning or
another paid run.

## Stop conditions

Stop after this one attempt, or if a provider layer exhausts its retries or a
registered CNY breaker trips. Preserve raw logs, run identifiers, cost totals,
configuration and elapsed time. No second paid run is allowed by this
registration.
