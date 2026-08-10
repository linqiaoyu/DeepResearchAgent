# 112 result

R111 closed its own list and named three things as "not established". This round
came from a different direction: a full review of the harness, asked for by the
user, which produced eleven findings ranked by severity. All eleven are closed
below. Two of them were not on R111's list and could not have been, because the
defect they describe had been passing every gate for 27 rounds.

## The finding that mattered

`document_version.filing_date` existed in the SQLite schema and in no migration.
A mechanical comparison of the twelve columns that `SQLiteStore._ensure_column`
adds against every `migrations/*.sql` found eleven present and one absent — this
one. The Postgres read path avoided the SQL error by not selecting the column,
so a missing schema object surfaced as an empty string rather than a failure.

That was the visible half. The larger half was that **no code had ever written a
filing date at all**, on either backend. `record_document_version` inserted
`(id, document_id, file_sha256, effective_date, status)` and nothing else. The
only writer in the repository was `scripts/backfill_085_filing_dates.py`, a
one-shot script that operated directly on one local SQLite file.

So the chain read:

```
filing_date = ""                              (no ingest path ever set it)
  → backends.py:33   published_at = None
  → search.py:210    (published_at or effective_date) <= as_of
  → the period end stands in for the disclosure date
```

A FY2025 annual report carries `effective_date = 2025-12-31` and is disclosed
months later. Substituting one for the other is lookahead bias, and the
substitution happened at four separate layers, each of which looked like a
sensible default in isolation.

**The exposure is measurable.** Rebuilding the corpus against the SEC EDGAR
submissions index dates all 60 documents exactly:

| | value |
|---|---|
| documents resolved | 60 / 60 |
| unresolved | 0 |
| distinct filing dates | 41 |
| disclosure lag, min | 53 days |
| disclosure lag, **median** | **109 days** |
| disclosure lag, max | 120 days |

For a median document, the old behaviour made it visible **109 days before it
was public**.

## What the corpus actually declared

R112 checked what the shipped manifests said, rather than what the pipeline did
with it:

| manifest | documents | disclosure date |
|---|---|---|
| `finance_v1.json` | 60 | no `published_at` field at all |
| `finance_v2.json` | 60 | all 60 identical: `2026-07-29`, tagged `retrieved_at_fallback` |
| `finance_v3.json` (new) | 60 | 41 distinct dates, all `sec_edgar_submissions` |

`retrieved_at_fallback` is the day the files were downloaded. It was honestly
labelled and still useless as a disclosure date — and because it was *later*
than any real filing date, an as-of query at the demo's own `2026-07-09` would
have excluded the entire corpus.

Both older manifests are immutable history under section 7 and were not edited.

## The other finding, one round late

R110 found Postgres tests that had skipped since they were written. R111 added a
CI job and a guard — and hardcoded the guard to two Postgres module names. R112
found `integration.test_qdrant_integration` in the identical state: skipping on
every run, no job supplying `DEEPRESEARCH_QDRANT_URL`, the vector index never
executed against a real service even once. The file held a single assertion,
that asking for a collection returned "exists" or "missing".

The lesson of R110 had been applied to the instance instead of the class. That
is now a rule with a check behind it: every skip must be declared in
`data/allowed_test_skips.json` with the CI job responsible for it, an undeclared
skip fails, and `--verify-workflow` fails when a declared job does not exist.

## All eleven findings

| # | finding | severity | closed by |
|---|---|---|---|
| 1 | `filing_date` had no write path → lookahead bias | P0 | SEC provider, corpus v3, both backends persist it, `check_disclosure_lookahead.py` |
| 2 | `document_version.filing_date` missing from Postgres | P0 | `migrations/006` |
| 3 | nothing reconciled the two schemas | P0 | `check_storage_schema_parity.py` |
| 4 | Qdrant skipped silently, never executed | P1 | `qdrant-vector-index` CI job, 4 real assertions, `check_no_silent_skips.py` |
| 5 | Postgres RAG methods had zero contract coverage | P1 | contract now asserts 8/8 protocol methods on both backends |
| 6 | `PostgresStore` inherited `SQLiteStore` without `super().__init__()` | P2 | composition; shared logic extracted to `storage/mapping.py` |
| 7 | Postgres accepted a `file_sha256` SQLite refused | P2 | single `validate_document_version()` both backends call |
| 8 | corpus disclosure provenance was a fallback | P2 | `finance_v3.json`, 60/60 from SEC EDGAR |
| 9 | no static type checking | P3 | `mypy --strict` on storage + domain protocols, file list is a ratchet |
| 10 | `docs/decisions/108` missing | P3 | reconstructed from surviving evidence, labelled as such |
| 11 | domain ratchet did not scan `prompts/` | P3 | ratchet extended; found and locked 2 previously invisible lines |

## Counterexamples

Every new guard was made to fail first, and the raw output is kept in
`_collab/112/counterexamples/`:

- `schema_parity_without_006.txt` — removing migration 006 reproduces the
  original drift: `column(s) ['filing_date'] exist in SQLite but not in migrations/`
- `pg_contract_without_filing_date.txt` — reinstating the Postgres mapping
  defect: `AssertionError: '' != '2026-03-20'`
- `disclosure_guard_on_corpus_v2.txt` — the guard rejects both older manifests
  (`60 of 60 documents have a substituted disclosure date`) and rejects the
  period-end fallback (`a filing disclosed 2026-04-15 was visible as of 2026-02-01`)
- `no_silent_skips_undeclared.txt` — removing the Qdrant declaration:
  `undeclared skip: integration.test_qdrant_integration...`
- `domain_ratchet_prompts_blindspot.txt` — extending the ratchet to `prompts/`
  immediately surfaces two unallowlisted files

## Downstream paths executed for the first time this round

Section 7 requires naming these, because a defect below a broken layer cannot
appear until the layer above works:

- **Postgres `rag_status` / `list_ready_chunks` / `resolve_ready_chunks`** — no
  test had ever called them. They pass now; the `filing_date` defect was found by
  reading them, not by running them.
- **The Qdrant write and query path** — `upsert`, `ensure_collection`, payload
  filtering and the as-of range filter all executed against a real service for
  the first time.
- **`ingest_and_persist` with a fully dated manifest** — every previous ingest
  ran with a substituted disclosure date, so the branch that carries a real one
  had never been taken.

## Not established

- **A second product domain.** Unchanged from R111. The `prompts/` finding is
  relevant here: two core prompts name finance metrics directly, and no
  mechanism yet lets a domain pack contribute prompt fragments. The ratchet
  locks the debt; it does not remove it.
- **That the four remaining `retrieved_at_fallback` consumers are gone.** The
  fallback is removed from the shipped corpus and refused by the guard, but
  `search.py:210` still contains an `or effective_date` expression. It is now
  unreachable for correctly dated documents and load-bearing only for legacy
  rows in existing databases, which are not migrated.
- **27 of the 30 golden questions have still never run at real fidelity.**
  Unchanged from R111; this round did not touch the evaluation instrument.
- **Whether any reported score changes under real disclosure dates.** Retrieval
  now sees a smaller, correct candidate set for any as-of before a filing date.
  No golden re-run was performed, so the effect on scores is unmeasured, and
  nothing here should be read as a quality claim.
