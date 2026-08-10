# 116 result

This round was scheduled as "open the research loop". Measuring first changed
what it should be: the agent already had the answers it was failing to give.

## What the measurement said

R113's 30 live states, read before any change:

| | |
|---|---|
| Evidence extracted | 2844 |
| Evidence reachable from a footnote the body cites | 782 (27%) |
| sub-questions researched, delivered with none of their Evidence cited | 8 of 80 |
| gold numeric facts reaching the reader | 25 of 50 |
| gold facts never retrieved | 12 |
| **gold facts retrieved, extracted, and then dropped** | **13** |

Selection loss was as large as retrieval loss. And the loop, had it been
switched on, would not have addressed either: 28 of 30 questions score
*insufficient* under the shipped thresholds, but Q16's gaps are
`counterargument`, `freshness` and `unresolved_critic_issues` -- never "the
market-share figure is missing". It would have iterated, in the wrong
direction, on a question whose evidence store already held the answer.

Two states show the shape of it.

**Q08** held, in its own evidence store, a sentence stating the period total,
its increase against the prior period, and explicitly that the question's
premise did not hold. The delivered report printed one provider row and nothing
else.

**Q16** held nine SNE Research items under `share_2024`. The draft wrote
「未获取SNE Research等第三方机构的官方装机量数据」 in its risk section and
answered a market-share question from revenue.

Neither is a retrieval failure. `context_events` records
`selected_count: 5, dropped_count: 0` for Q08 and `142/13` (duplicates only) for
Q16, and `draft_report` is byte-identical to the final report. The model saw the
evidence and passed over it; nothing downstream of the model removed anything.

Widening the pipe before fixing the funnel would have dropped more evidence in
the same place, so this round fixed the funnel.

## Three defects

1. **No floor.** A sub-question the draft ignores produces no reader-visible
   line at all, and is indistinguishable from one that returned nothing.

2. **The typed re-rendering deletes the analysis.** `_evidence_claim_text`
   replaces a data claim with its typed fields so a paraphrase can never display
   a wrong value. It does that by discarding the sentence -- including
   everything the sentence said besides the value. On Q08 the value survived and
   the comparison and the refutation did not. The guarantee that rule protects
   is that a *disagreeing* value is never shown; when a claim's own numbers
   contain the typed value, there is nothing to disagree about.

3. **Confidence ranks trust, not relevance.** Every structured provider row
   carries 0.98 and every extracted sentence 0.85--0.95, so a floor ranked by
   confidence gives a market-share question two net-profit rows. Overlap with
   the sub-question's own wording now breaks the tie first; confidence still
   orders items that answer it equally well.

The first fix alone closed all 8 orphans and recovered **zero** gold facts,
because the losses were in sub-questions the draft *had* cited -- just not for
the evidence that answered them. That negative result is why the rule is "this
sub-question's best evidence reaches the reader" rather than "this sub-question
is mentioned".

## Counterfactual

The floor is deterministic given a state, so its effect was measured by calling
the shipped code with the saved states' own inputs -- same Evidence, same
footnote map, same set of citations the delivered report made. Identical inputs,
one change:

| | before | after |
|---|---|---|
| orphaned sub-questions | 8 | 0 |
| gold facts reaching the reader | 25/50 | **30/50** |
| `false_premise_failed` | 2/2 | **1/2** |
| Evidence reachable by the reader | 782 (27%) | 1208 (42%) |
| reader lines added | | +76 total, 2.5 per report, against a 32-line body |

Questions that gained a gold fact: Q08, Q09 (+2), Q14, Q16.

Q08's floor line is the sentence it had all along, and R115's criterion flips to
*refuted* on a real archived state.

Q16's floor now prints 「宁德时代2024年仍居全球动力电池装车量第一，市占率37.9%…
未被比亚迪反超」 -- cited, from its own evidence. It still fails the criterion,
correctly: the gold requires all four figures and one is present.

This was preferred to a fresh live run. Re-running the same questions today
would change retrieval and sampling as well as the code, and could not isolate
this change; no paid run was needed, and none was made.

## What this does not establish

- **Q16's report now contradicts itself.** The summary asserts the premise and
  the analysis refutes it with cited evidence. That is better than asserting it
  unopposed, and it is not correct. The summary is model-authored and no guard
  reads it against the report's own body.
- **The research loop is still off**, and the 12 gold facts that were never
  retrieved are still not retrieved. That is the next round, and the sufficiency
  gaps it iterates on need to name the question's own target first.
- **The counterfactual is not a live run.** It proves what this code does to
  those states; it does not re-measure the product end to end.

## Gate

Four full runs; the first three were red and their output is kept.

| run | result |
|---|---|
| 1 | `failed_step=unittest` -- `test_reporter_renders_uncited_claim_when_evidence_ids_are_missing` asserted the cited form appeared nowhere in the report; the floor now prints it under 详细分析 |
| 2 | `failed_step=unittest` -- the repaired assertion split sections on `"\n##"`, which matches `###`, so it read an empty section |
| 3 | `failed_step=domain_boundary` -- `ratchet mismatch: reporter.py observed=7 allowed=4`; the new docstrings quoted domain vocabulary. Rewritten domain-neutrally, back to the baseline 10 hits |
| 4 | green |

```
Ran 1128 tests in 58.312s
OK (skipped=7)
[tracked_files_unchanged] gate created no tracked changes
gate_exit=0
```

Test count 1111 → 1128. Skips unchanged at 7, all registered.

Three tests were adjusted, each because the floor adds reader lines they counted
by position or in total. None had its subject weakened:

- `test_unverified_margin_backsolve_is_downgraded` selected claim provenance by
  index; it now selects by path, which asserts *which* claim was downgraded.
- `test_reporter_renders_uncited_claim_when_evidence_ids_are_missing` asserted a
  cited form appeared nowhere; it now asserts the model's own claim carries no
  citation, which is what the test is for.
- `test_sections_sharing_a_sub_question_id_all_reach_the_reader` asserted two
  cited lines; it now asserts authored lines plus floor lines, with
  `rendered_lines == 2` unchanged.
