# 117 result

R116 measured what the reader receives. This round acted on the largest number
in that measurement: of 1269 reference lines delivered across the 30 R113 live
reports, the body cited 213. **83% of every reference line on the page was a
line nothing pointed to.**

## Two independent causes

**The footnote key.** `build_footnote_maps` grouped by `source_url`. R107 added
that so two sentences read out of one filing share a footnote -- correct for a
document, wrong for a provider series, where each record carries its own
`scheme://metric/symbol/date/hash`. 969 of the 1269 reference lines were single
records of a series. One report ran to 766 lines, 736 of them references, three
of them cited: 242 trading days times three price fields.

This is R107's defect in the source class R107 did not cover, which is what
AGENTS.md section 8 means by fixing the class rather than the instance. The key
is now the scheme and title for a provider series -- what it is a series *of* --
and still the URL for a document, so two metrics from one provider stay apart.

**The rebuild pass.** `_enforce_reader_fidelity` rebuilds the page from the
sections it keeps, dropping a risk line the domain judges invisible, an
assumption section, an analysis section on fallback -- and copied the reference
list across untouched. Every footnote cited only from a dropped section survived
with nothing pointing at it.

This one was found by disbelieving the first fix: filtering inside the renderer
left the demo printing five references for three citations, and the reason was a
third code path neither edit had touched.

## Result

Applied to the 30 saved R113 states:

| | before | after |
|---|---|---|
| reference lines | 1269 | **163** |
| never cited | 1056 (83%) | **0** |
| provider-series references | 969 | **50** |
| total report lines | 2261 | **1143** |

The worst cases: 736 references become 3, 118 become 4, 60 become 23.

Both render paths carried the same reference block written out twice. It is one
method now. Numbers are not reassigned -- a gap in the sequence is visible and
harmless, while renumbering would mean rewriting markers already rendered above
and republishing `report_footnote_evidence` to match, and a mapping that
disagrees with the page is the failure that contract exists to prevent.
`[records=N]` is new: a footnote standing for a series prints the URI of one
record of it, and the count is what tells the reader the marker covers more.

## Enforcement

`scripts/check_reference_list_hygiene.py` runs in the gate twice -- on its own
self test, and against the demo report the gate has just produced, so the
assertion is on a delivered artifact and not only on a fixture. Its self test
covers five cases, including both directions of the grouping change: 50 records
of one provider series must produce one reference, and five distinct documents
must still produce five.

## Snapshots

Four characterization snapshots changed, one field each. Attributed per hunk
before regenerating: in all four the reader-visible body is byte-identical, the
removed lines are exactly those whose footnote number appears in no marker on
the page, and the surviving references gained `[records=N]`. Committed
separately from the code.

## Not established

- **Citation granularity.** A claim about a year of price movement can still
  cite a footnote that stands for 242 daily records. The reference now says so
  with `[records=242]`; it does not point at the day the claim rests on.
- **The body is unchanged.** This round removed noise around the report. What
  the report says is R116's floor and the rounds after it.

## Gate

```
Ran 1128 tests in 64.727s
OK (skipped=7)
reference_list_self_test=PASS cases=5
reference_list=PASS references=3 body_lines=14 never_cited=0 unresolved=0
[tracked_files_unchanged] gate created no tracked changes
gate_exit=0
```

One red run preceded it: `failed_step=unittest`, the four characterization
snapshots, which is the change above and was resolved by attributing and
regenerating them.
