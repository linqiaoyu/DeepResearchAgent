# T8 SEC Company Facts live validation preregistration

Date: 2026-08-02
Commit: recorded by the commit that introduces this file.

## Authorization and hypothesis

The user authorized exactly one T8 paid live attempt: CNY 15 per attempt and
CNY 20 for the whole round.  The hypothesis is that, after the completed SEC
Company Facts provider repair, one bounded live run can deliver a non-empty
report, an audit citation closure, and a complete active-provider manifest
while real SEC 20-F structured financial facts and real RAG are used.

## Frozen configuration

- Code baseline: `d4be252` plus this preregistration commit.
- Topic: `阿里巴巴 2024 年 20-F 财务表现与风险因素研究`.
- `as_of`: `2026-07-01`; depth: `1`.
- Structured provider: `sec_companyfacts`.
- RAG database: `data/runtime/047-assets.db`.
- RAG index version: `finance_v1-43f11085-heading_page_first_1024_256`.
- Mode: `live --allow-paid-api`.
- Workflow LLM hard budget: CNY 3; RAG hard budget: CNY 12; combined
  registered ceiling: CNY 15.

## Measurements and acceptance

The single run must preserve its configuration, write a non-empty `report.md`
with `audit_citation_closure: ok`, preserve the declared retrieval index
version, write at least one RAG embedding or rerank ledger row, and keep the
workflow manifest `cost_cny_total <= 15`.

Assessment uses `scripts/check_real_run_manifest.py --require-active-real`:
LLM, search and RAG must each be used with real fidelity.  SEC structured data
must either be real when used or explicitly unused without a degradation event;
the expected Alibaba financial request is real SEC use.  Disclosure remains
optional under the user-approved active-provider acceptance policy.  The raw
manifest may be `mixed` if disclosure is truly unused.

## Stop and rollback rules

Do not tune or retry this code version.  Stop this attempt immediately if any
provider layer exhausts its three retries, the CNY 15 single-attempt or CNY 20
whole-round breaker trips, or package delivery fails.  Preserve the raw log,
run IDs, manifest, ledger totals, elapsed time, and all negative outcomes.
Any repair after this run requires a new authorization and preregistration.
