# 100 result

`reader_analysis_lines=2` against a threshold of 2, on the same topic that
returned 0 in all seven previous live runs. The reader receives authored,
cited analysis for the first time in this project's history.

## What the reader now gets

```
## 详细分析
### 蔚来 2023 与 2024 年营收和毛利率的变化及其驱动因素
- 2024年第四季度汽车交付量达7.27万辆，全年交付21.20万辆，交付量提升直接拉动
  汽车销售收入增长。 [^1]
- 2024年全年净亏损224.017亿元，尽管营收增长，但费用投入远超收入增速，导致
  亏损扩大。 [^1]
```

Against R099's delivery of the same topic, which had no `## 详细分析` at all.

## Five rules, each removing a loss the previous one exposed

R099 established that the reporter no longer falls back. What remained was
five separate deletions between the reporter's draft and the reader's page.
Each became visible only once the one above it was fixed, and each was
measured on the failing run's own claims rather than reasoned about.

**1. A repeat was any sentence containing a digit.**
`_RESTATES_NUMBER_RE = re.compile(r"\d")`, while `prompts/reporter.md` asks
only that a key finding not be repeated *verbatim*. Every analysis line about
a metric named in `关键发现` carries a year, so the rule deleted the analysis
and put nothing in its place — 2 of 3 claims in R099's last run. The test now
measures what a repeat costs a reader: the claim's content characters against
the lines already emitted. Restatements score 0.88–0.92, explanations of the
same metric 0.11–0.33, and the threshold sits at 0.80 in that gap.

**2. A margin claim was compared against itself under a different name.**
The numeric fidelity guard rescoped a claim's generic `毛利率` to
`主营业务毛利率` whenever the question required that metric, while the evidence
side rescopes only when a typed total-row field anchors it — which retrieved
web text never carries. A claim quoting
`2024年蔚来的汽车毛利率为12.3%，同比增加2.8个百分点` word for word was declared
unsupported by the sentence it came from. The claim is now rescoped only where
its evidence was.

**3. `较2022年的10.4%` was read as a change, not last year's level.**
The rule that recognises a comparison base already existed, and its comment
already said so — `较2024年的1,708.99亿元` — but its pattern listed only
currency units. A rate base fell through to the change branch and did not
match the level the evidence stated.

**4. Topicality required sharing evidence with a key finding.**
When every required metric comes back a gap, the reader's `关键发现` is a list
of notices citing nothing, so there is nothing to share. Four claims about
this question's own revenue and margin drivers were filed as off-topic and
deleted with `补充事实`. A sentence naming the metric the question asks about
is on topic whatever it cites. The domain owns that judgement:
`metrics_mentioned` is a new `ReportingDomain` method, so core learned no
metric name and `import_sites=0 literal_files=3 literal_hits=8` is unchanged.

**5. A footnote resolved to one source when it stands for several.**
`build_footnote_maps` gives one number to every Evidence sharing a source. The
fidelity downgrade inverted that mapping with a dict comprehension, which keeps
one entry per key. In the second run footnote 1 covered a margin extract and a
revenue extract: the revenue line resolved correctly and survived, the margin
line resolved to the same revenue extract and was replaced by
`该数值表述未通过 Evidence 保真守卫` while quoting its own source.
`has_numeric_mismatch` already documents its evidence argument as a union; it
now receives the union.

## Live validation — three runs, same topic as the R099 baseline

| | R099 E3 | E1 `9e6ab02` | E2 `7f8cc59` | E3 `d6e3ef2` |
|---|---:|---:|---:|---:|
| `reader_analysis_lines` | 0 | 0 | 1 | **2** |
| `reporter_fallback` | 0 | 0 | 0 | 0 |
| `rendered_lines` | 0 | 3 | 4 | 4 |
| `claims_dropped_duplicate_number` | 2 | 0 | 0 | 0 |
| `claims_dropped_unrelated` | 1 | 4 | 0 | 1 |
| `downgraded_numeric_lines` | — | 5 | 5 | 2 |

E1 fixed the repeat rule and moved the loss downstream rather than removing it:
three lines rendered, all three replaced by the same notice. E2 fixed three
causes at once and reached 1. E3 fixed the footnote union and reached 2.

The one claim still dropped as unrelated is
`2024年第四季度净亏损71.115亿元，经营亏损60.329亿元` — a loss figure for a
revenue-and-margin question, correctly filed, and now visible with its text
rather than as a count.

## Counterexamples

Each saved with its real failure output under `_collab/100/evidence/`.

| guard | mutation | failure |
|---|---|---|
| repeat test | restore `re.compile(r"\d")` | `an explanatory line was deleted as a repeat: 2024年营业收入3620.13亿元的增长主要来自…` |
| margin rescope | rescope the claim regardless of its evidence | `AssertionError: True is not false` |
| comparison base | restore the amount-only unit list | `AssertionError: True is not false` |
| topicality | drop the `metrics_mentioned` term | `'## 详细分析' not found … the reader received no analysis section at all` |
| footnote union | restore the last-wins lookup | `'未通过 Evidence 保真守卫' unexpectedly found … a line quoting its own source was deleted as unverifiable` |

## Gate

`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/gate.py` -> `gate_exit=0`,
`Ran 876 tests ... OK (skipped=4)`, `gate created no tracked changes`,
`import_sites=0 literal_files=3 literal_hits=8` — the domain-boundary ratchet
did not grow. A first attempt was correctly rejected by `TID251` for importing
`domains.finance` into a core test; the tests reach those rules through the
injected pack instead, which is also what the reader-visible behaviour depends
on.

## Spend

CNY 0.5236 across three runs (0.175227, 0.159011, 0.189389), each inside the
per-run breaker of 0.6.

## Still open, by line

- **INCOMPLETE (medium)**: 2 of 4 rendered analysis lines are still replaced by
  `该数值表述未通过 Evidence 保真守卫`, and the notice is emitted once per line,
  so a reader sees the same sentence twice. Deleting the line outright would
  read better than repeating boilerplate; neither was in this round's scope.
- **INCOMPLETE (medium)**: `structured_parse_errors=3` and `truncated_calls=1`
  in E3, neither diagnosed. The R098 payload dump covers both.
- **INCOMPLETE (low)**: a rendered line carries `[^1] [^1]` — the same footnote
  twice, from two evidence ids sharing a source.
- **Note on stability**: `reader_analysis_lines` is 2 in this run and was 0 and
  1 in the two before it, on the same topic and prompt. What retrieval returns
  varies, so the live number varies. The five guards are offline and
  deterministic; the live figure is one observation, not a floor.
