# T8 real three-layer E2E pre-registration

## Authorization and hypothesis

User explicitly authorized T8 at most CNY 15 on 2026-08-02. Hypothesis: one
bounded live run using real LLM, retrieval, and structured/search providers,
with a configured Qdrant RAG index, produces a non-empty cited report and a
complete manifest whose `actual_realness` is `real`.

## Measurement and decision rule

The sole registered attempt is measured by report existence, manifest
`actual_realness`, manifest `retrieval_index_version`, audit citation closure,
and the RAG ledger's embedding/rerank rows and CNY total. No retry, tuning, or
second run is allowed after the provider call begins. A failed result is recorded
as failed; any code repair and subsequent attempt needs new authorization.

## Cost controls and rollback

Single-run circuit breaker: CNY 15 (workflow LLM CNY 3 plus RAG CNY 12).
Round circuit breaker: CNY 20. Any provider layer exhausting its three allowed
attempts stops this run. The rollback condition is any budget breach, missing
provider configuration, unreachable index, or terminal provider failure: retain
the evidence and make no paid call (preflight) or no further paid call (after
start).

## Scope

Topic will be a company present in the indexed corpus, with `as_of` later than
the corpus `published_at`. This document is committed before preflight/provider
work and does not authorize any external write beyond the one paid provider run.
