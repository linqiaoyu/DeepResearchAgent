# 110 result

R109 closed by saying the harness implementation was "about 85% complete". That
number was too coarse to act on, so R110 re-measured it, and re-measuring
dissolved three of the five things it counted:

- The three graph nodes that never fire by default are implemented and work.
  With their flags on, R109's own live arms fired `research_loop_decide` 8×,
  `research_refine` 2× and `reflector` 6×. They are switched off, not missing.
- `NotImplementedError` appears exactly once in 34,824 lines of source, and it
  is a deliberate fail-loud for an unconfigured search provider.
- The Postgres backend was never broken, only unverified.

Five real gaps remained. All five are closed, each with a counterexample
recording the failure when the fix is reverted.

## A capability that was on and inert, again

`RagSearchService` was constructed **zero times** in `src/`. Its only
construction site was a script, and `capability_setup` substituted the pre-index
implementation whenever a caller passed nothing — so `RAG_ENABLED=true` through
the engine could not retrieve anything. R109's live A/B arm had already recorded
the symptom (`provider_fidelity.rag_search='fixture'`, `not_found/empty_result`,
zero candidates, three cases) without the cause being identified.

This is the second instance of the pattern R109 named with
`RESEARCH_LOOP_ENABLED`: a documented capability an operator can switch on that
cannot take effect. The fix is the boundary every sibling capability already
has — `build_rag_search` beside `build_search_provider` and
`build_structured_data_provider` — plus a refusal that names every missing
variable instead of degrading in silence.

Verified against the real stack: the R087 SEC corpus (22,953 chunks, 60
documents) and the live Qdrant collection returned 8 candidates with
`fidelity: real` and zero degradations, for CNY 0.028 of embedding and rerank on
the ledger the factory wires up.

## Extensibility was a registry with one entry

`load_domain_pack` accepted `"finance"` and raised for everything else, while
`Settings.domain_pack` reads `DEEPRESEARCH_DOMAIN_PACK` from the environment.
`NullDomainPack` — 234 lines proving the workflow composes with no metric
vocabulary, no disclosure policy and no numeric interpretation — was reachable
only by injecting it inside a test.

Both are now installed. `DEEPRESEARCH_DOMAIN_PACK=null` completes a workflow
through the registry and produces a cited report carrying none of the finance
sections. `null` is not a product domain; it exists so the harness can be held
to what it does without one, through the path an operator uses.

The domain interface is still 14 protocols and 86 method signatures, of which
the finance pack implements 51. A second *product* domain remains unwritten,
and this round does not claim otherwise.

## What a run can prove about itself

Answering "did this capability run?" required knowing which metadata key or
artifact to read, and R109 got two of those answers wrong — the manifest and the
trajectory are written under `runs/<research_id>/`, not into the state. Writing
the locator table down caught a third: structured output is a top-level
`ResearchState` field, and looking for it in metadata reported a capability that
ran in all 24 archived live runs as absent in all 24.

Measured across those 24 runs: **16 of 25** declared flags are provable from a
run's own artifacts. The other 9 leave no per-run evidence at all. They are
listed by the checker and pinned by a test so the list cannot shrink silently.

## A gate that would have blocked correct documentation

Six documentation statements contradicted the code and had passed every gate,
because the settings sync validates `FLAG=value` tokens in three files and
nothing read the sentences.

The first rule written for this bound a claim to any flag token near it. On the
real documents it measured **2 of 3 precision**: it read "`rag_search` is
conditionally registered only when `RAG_ENABLED=true`. Its current default is …"
as a stale default claim. That rule was dropped rather than shipped. Binding now
stops at a clause boundary, and the nine remaining tokens that differ from
`Settings` were each read and confirmed to be conditionals or enable-examples,
which the checker deliberately leaves alone.

## Not established

- A second product domain. The registry now proves a domain is selectable; it
  does not prove the 51-method interface is comfortable to implement.
- The 9 capabilities with no per-run evidence.
- Postgres in CI. It is verified on demand, at 172 seconds, and stays out of the
  default gate.
- The finance symbol-resolution defect, which is the largest measured product
  gap and was deliberately out of scope.
