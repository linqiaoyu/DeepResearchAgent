# 113 result

R112 closed with four items under "not established". This round takes all four,
and the first one is closed by a decision rather than by code.

## The item that was never a defect

"There is no second product domain" had been carried as an open gap since
020-I. Twenty-plus rounds reported it, R112 reported it again, and the framing
was wrong in a way that invites a bad fix: it treats a product decision as
debt, and the cheapest way to discharge debt is to invent a second domain
nobody asked for.

The user's decision is that finance is the domain being finished. The
`DomainPack` seam stays -- it is what makes finance itself replaceable,
testable and auditable -- and no second domain is started.

That is now written in `AGENTS.md` section 1 with an enforcement surface, so
it cannot quietly drift in either direction:

```
import_sites=0 literal_files=5 literal_hits=10 lexicon_terms=33 product_domains=1
```

`product_domain_packs()` excludes the `null` harness fixture, which is
registered and tested but is not a product domain and must never be counted as
evidence the framework is domain-general. `check_domain_boundary.py` asserts
the set both ways: adding a second product domain fails, and so does losing
this one. Injecting one produces

```
product domains are ['finance', 'legal'], declared ['finance'].
```

The consequence for the ten allowlisted finance literals in core is that they
are **accepted product debt**, not a gap somebody must repay. The ratchet's job
changes from prompting repayment to preventing growth. Nothing else relaxes:
`import_sites` stays 0 and the ratchet still only shrinks.

## The item R112 under-reported

R112 said the `or effective_date` in `search.py` was "unreachable for correctly
dated documents and load-bearing only for legacy rows". That was too generous,
and checking it properly showed why.

The substitution had not been removed. It had moved earlier:

| layer | what it did when no disclosure date was declared |
|---|---|
| `ingest_and_persist` | passed `entry.published_at or entry.effective_date` |
| `validate_document_version` | returned `published_at or effective_date` |
| chunk `INSERT` (both backends) | wrote `chunk.published_at or effective_date` |
| `search.py` | `(published_at or effective_date) <= as_of` |

So a fresh ingest of any manifest without disclosure dates wrote the period end
into the database *as* the disclosure date. That is not a smaller version of
the R112 bug. It is the same bug promoted from a default to data, where it no
longer looks like a fallback at all.

All four sites are gone. Unknown now means withheld, and the reason is
mechanical rather than a preference: an empty string sorts before every real
date, so a plain `published_at <= as_of` would make precisely the chunks nobody
can vouch for the ones that are *always* visible. `AS_OF_PREDICATE` is shared
between the backends so they cannot disagree about it, and `search.py` records
a `DegradationEvent` naming how many chunks it withheld, so recall lost this
way is visible instead of silent.

`check_disclosure_lookahead.py` gained `undated_withheld`, which asserts an
undated document is invisible at every as-of including `9999-12-31`. It failed
the moment it was written -- that is how the second `INSERT` site was found,
after the first three had already been fixed.

Legacy databases are migrated by `backfill_disclosure_dates.py`, which
re-resolves anything whose `filing_date` equals its period end (the fingerprint
of the old write path) and clears what SEC EDGAR cannot confirm rather than
leaving it back-dated. On a legacy-shaped database: 6 of 6 rows moved from
period end to real filing dates, 0 unresolved.

| period end | before | after |
|---|---|---|
| 2022-03-31 | 2022-03-31 | 2022-07-26 |
| 2022-12-31 | 2022-12-31 | 2023-03-22 |
| 2023-12-31 | 2023-12-31 | 2024-03-15 |
| 2024-12-31 | 2024-12-31 | 2025-03-28 |

The real 60-document corpus is unaffected, because its dates were already real:
457 / 15,783 / 22,953 chunks visible at 2023-01-31 / 2025-02-28 / 2026-01-15,
identical to R112.

## Five test fixtures, and why changing them is not weakening them

Removing the fallback broke five RAG tests. All five built chunks with no
disclosure date and relied on the removed substitution to be visible at all.
Each now declares its disclosure date, which is exactly the behaviour change:
the system no longer guesses, so the fixture states the fact. No assertion was
weakened, none was deleted, and the one test that specifically covers the
distinction -- `test_as_of_filters_on_published_at_not_report_period` -- was
already passing and still is.

## Golden set at real fidelity

R109 gave the runner a live arm and used it on three questions. R111 and R112
both closed by noting the other 27 had never run at real fidelity. They have
now.

| | |
|---|---|
| fidelity | live -- LLM, retrieval, structured data and judge all real |
| **coverage** | **30/30** (was 3/30) |
| failed questions | 0 |
| judge samples | 3 per question |
| spend | CNY 14.99 |

Deterministic outcomes, which are the ones worth quoting:

| metric | value |
|---|---|
| `citation_resolution_rate` | median **1.000**, min **1.000** |
| `uncited_claim_rate` | median **0.000**, max 0.167 |
| `false_premise_failed` | **0/30** |
| questions returning zero evidence | **2/30** (Q03, Q05) |

### The noise floor, before any score

Section 8 requires the noise floor first. Across the three judge samples of the
same question:

| dimension | median spread | max spread |
|---|---:|---:|
| fact_coverage | 0.050 | 0.50 |
| fact_accuracy | 0.100 | 1.00 |
| citation_support | 0.150 | 1.00 |
| synthesis_balance | 0.100 | 0.30 |

And the per-question medians (n=30): fact_coverage 0.330, fact_accuracy 0.750,
citation_support 0.675, synthesis_balance 0.450.

**No capability conclusion is drawn from those.** This is a single arm with no
control, two dimensions have a within-question spread reaching 1.00 -- the full
range of the scale -- and section 7 forbids comparing them to the historical
fixture numbers, which were measured at a different fidelity. What this round
established is coverage and the deterministic metrics above.

### Execution, and two recorded amendments

Serial execution measured 194 LLM calls at 21.6 per question and a 31.6s median
latency, so **64% of wall clock was spent waiting on the provider** and 10
questions took 2h50m. Amendment 1 sharded the remaining 20 across four
concurrent processes: 1h40m, about 5 minutes per question effective.

Q09 failed in the serial phase. Not on a budget -- on a provider connection
error during judging, after 2249 seconds of successful research. Its
`state.json` was intact (`status=done`, 105 evidence items), because state is
written before scoring, so amendment 2 re-judged that saved state rather than
re-running the research. `merge_golden_shards.py` accepts exactly one kind of
duplicate -- a failure superseded by a recovery -- records what it replaced,
and errors on two successful scores for the same question so that "pick the
better one" is not available.

## Not established

- **That the golden scores mean anything yet.** A single live arm has no
  control. Fidelity coverage is what improved.
- **Prompt-level domain injection.** The two core prompts still name finance
  metrics directly and no mechanism lets a pack contribute prompt fragments.
  Under the new scope this is accepted debt with a ratchet, not a planned fix.
- **Legacy databases in the wild.** The migration exists and is verified, but
  only the local runtime databases were migrated; nothing scans for others.
