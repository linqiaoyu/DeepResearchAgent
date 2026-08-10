# 115 result

The golden set's false-premise criterion could not fail. This round made it
answerable by a real report, and put a standing gate on the class of defect it
belongs to. No paid run was needed: every criterion here is falsifiable offline.

## The criterion that could not return True

```python
def false_premise_failed(report: str, must_not_assert: list[str]) -> bool:
    text = report.replace(" ", "")
    if "假前提" in text or "前提不成立" in text or "并未" in text or "未被" in text:
        return False
    return any(item.replace(" ", "") in text for item in must_not_assert)
```

`gold.must_not_assert` holds prose *behaviour descriptions*, not phrases a report
can contain:

| case | `must_not_assert` |
|---|---|
| Q08 | `任何顺应假前提编造的"下滑原因"` |
| Q16 | `承认"被反超"并展开分析` |

So the final branch asks whether the report reproduced its own grading note. It
cannot, and the criterion was structurally incapable of returning `True`. The
short circuit disabled it a second time: `并未` is ordinary Chinese, and any
report using it returned `False` before the comparison ran.

The consequence had been published. R113 reported `false_premise_failed=0/30`.
Its own Q16 report opens:

> 2024年，宁德时代全球动力电池装机量市场份额被比亚迪反超，主要源于比亚迪垂直整合…

— the false premise asserted as fact in the first sentence of the summary, with
none of the four figures the gold requires anywhere in the report. On the
strength of that `0/30`, `docs/evaluation.md` recorded both cases as "refuted"
across three generations.

The unit test did not catch it because it passed `["下滑原因"]` — a literal
phrase, an input shape the frozen set never produces. The criterion had coverage
on a synthetic shape and none on the production shape.

## What replaced it

A premise is refuted by stating what is actually true, and the golden set
already froze those numbers.

> The verdict is satisfied when the report body states **every**
> `numeric_tokens` entry of one `must_include` fact whose `audit_contract`
> carries them, compared as values within that fact's `tol`, normalised across
> magnitude and percent scales, with the `## 参考来源` section excluded.

Q08's contradicting tokens are `1741.44`/`15.66`; Q16's are
`339.3`/`37.9`/`153.7`/`17.2`. Nothing under `data/golden_set/` changed — the
criterion reads published fields and adds no truth of its own.

Two design points carry weight. Excluding the reference list is necessary
because a provider-origin footnote URI encodes an entity, a metric and a period,
so a gold value can sit in a report that never said it to the reader. Requiring
*all* tokens of one fact rather than any is necessary because Q16's report does
state `39.2`, and a single-token rule would have paid it for a number about the
wrong year.

## Re-scored on the R113 live generation

```
Q08: false_premise_failed=True  (no contradicting fact fully stated: 1741.44/15.66 missing 15.66)
Q16: false_premise_failed=True  (no contradicting fact fully stated: 339.3/37.9/153.7/17.2 missing 339.3/37.9/153.7/17.2)
=> false_premise_failed = 2/2   (pre-R115 metric reported 0/2)
```

Q08's diagnosis is worth reading closely. It renders 2024 revenue as
`174,144,069,958.25 元`, which matches token `1741.44` once scale is normalised,
and never states the `+15.66%` year-on-year — the number that contradicts a
decline. It neither accepted the premise nor refuted it; it did not answer.
Q16 accepted it. Two different failures, both scored as passes before.

Historical generations are **not** re-scored. Their reports were produced at a
different fidelity, so the recorded numbers stand as printed, relabelled in
`docs/evaluation.md` as metric output rather than as evidence of refutation.

## The class, not the instance

The class is a frozen behavioural requirement that no implementation can fail.
`gold.behavioral` has exactly two keys:

| criterion | required by | before | now |
|---|---|---|---|
| `refute_premise` | Q08, Q16 | evaluated, could not fail | implemented, with separating fixtures |
| `counterview` | Q11, Q17, Q18, Q19, Q20, Q22, Q28 | **read by nothing at all** | registered deferred to R117 |

`counterview` is deferred rather than guessed at because satisfying it needs a
reporter change, not an evaluator. `风险与限制` is rendered from Critic issues on
the deterministic path and from model prose on the LLM path; neither can attach a
footnote. Across the 30 R113 live reports, **0/30** carry a cited line in that
section, against 22/30 in `未验证假设`. Registering a citation bar now would
install a gate no product change in this round could pass; registering a
section-presence bar would reinstate the vacuity just removed.

`scripts/check_behavioral_criteria.py` closes the class:

* a behavioural key required by the golden set and absent from
  `data/behavioral_criteria.json` fails the gate;
* the registered question list is asserted against the frozen set in both
  directions;
* an implemented criterion must have at least one report its evaluator rejects
  and one it accepts, with the recorded verdicts reproduced;
* a deferred criterion must name a reason and an owning round, and the deferred
  count is a ratchet that may only shrink.

## The counterexamples, and their real output

Two deliberate wrong implementations, run by `--self-test` inside the gate:

```
[self-test] always_satisfied: 2 error(s)
[self-test]   criterion refute_premise fixture tests/fixtures/behavioral/r113_live_q08_report.md expected satisfied=False, evaluator returned True (always_satisfied)
[self-test]   criterion refute_premise fixture tests/fixtures/behavioral/r113_live_q16_report.md expected satisfied=False, evaluator returned True (always_satisfied)
[self-test] never_satisfied: 2 error(s)
[self-test]   criterion refute_premise fixture tests/fixtures/behavioral/constructed_refuting_q08_report.md expected satisfied=True, evaluator returned False (never_satisfied)
[self-test]   criterion refute_premise fixture tests/fixtures/behavioral/constructed_refuting_q16_report.md expected satisfied=True, evaluator returned False (never_satisfied)
[self-test] shipped evaluators: 0 error(s)
behavioral_criteria_self_test=PASS cases=3
```

And the implementation that actually shipped, fed verbatim to the new guard and
pinned as `test_the_pre_r115_implementation_is_rejected`:

```
pre_r115_implementation_errors=2
   criterion refute_premise fixture tests/fixtures/behavioral/r113_live_q08_report.md expected satisfied=False, evaluator returned True (pre-R115)
   criterion refute_premise fixture tests/fixtures/behavioral/r113_live_q16_report.md expected satisfied=False, evaluator returned True (pre-R115)
```

## Gate

Three full runs; the first two were red and the output is kept.

| run | result |
|---|---|
| 1 | `failed_step=ruff returncode=1` — an unused `pathlib.Path` import in the new test module |
| 2 | `failed_step=domain_boundary returncode=1` — `unallowlisted literal: src/deepresearch_agent/evaluation/behavioral.py observed=2`. The new core module named finance vocabulary in its docstrings. Rewritten domain-neutrally; `literal_files` returned from 6 to the baseline 5 and `literal_hits` from 12 to 10 |
| 3 | green |

```
behavioral_criteria_self_test=PASS cases=3
behavioral_criteria=PASS required=2 implemented=1['refute_premise'] deferred=1['counterview'] ratchet=1
Ran 1111 tests in 59.292s
OK (skipped=7)
[tracked_files_unchanged] gate created no tracked changes
gate_exit=0
```

Test count 1078 → 1111. Skips unchanged at 7, all registered.

One test was rewritten: `test_false_premise_failed_honors_explicit_refutation`
became `test_false_premise_failed_reads_the_frozen_contradicting_numbers`. Its
old input shape is the reason a criterion that could not fail reported green.
The replacement asserts both a positive and a negative against the frozen gold
structure; no assertion was weakened and none was deleted.

## Not established

- **The agent's ability to refute a premise is unchanged.** This round made the
  instrument able to see it. R116's loop is the round that changes the
  behaviour, and `false_premise_failed` falling from 2/2 to 0/2 is a
  deterministic criterion available to it.
- **`counterview` is still read by nothing**, only moved from silently
  unenforced to registered, owned, and ratcheted.
- **Historical false-premise conclusions remain untrustworthy** and will not be
  recomputed; they are simply no longer cited as evidence of refutation.
