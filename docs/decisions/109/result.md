# 109 result

R109 was asked to do three things in order: run the golden set at real
fidelity, fix the report that contradicted itself and make that contradiction a
gate failure, and then decide the eight dark `content_affecting` flags on that
instrument.

The first step invalidated the third's premise, and finding that out was worth
more than the flag decisions would have been.

## The golden runner had never run at real fidelity

Every score this project has cited since round 008 — g1 `0.8337`, g2 `0.7714`,
g3 `0.7982` — came from a runner that hardcoded replayed search and a fixture
structured-data provider. `scripts/run_golden_round.py` had no switch for
anything else. Under `AGENTS.md` §6 a `content_affecting` capability may not be
promoted on fixture metrics, so the instrument that was supposed to decide the
dark flags could not have decided any of them.

The gap is not a rounding. Same question (Q01, 贵州茅台 2024, difficulty 易),
same gold answers, two fidelities:

| | fixture arm | live arm |
|---|---|---|
| `structured_data_stats.records` | `0` | `2` |
| coverage status | `searched_unavailable` | `cited` |
| bullets carrying a figure | 2 of 8 | 11 of 25 |
| gap notices in 关键发现 | 2 | 0 |
| 归母净利润 delivered | — | `86,228,146,421.62 元` |
| 营业收入 delivered | — | `174,144,069,958.25 元` |

Both figures match the gold set. The fixture instrument was not measuring a
weak product; it was measuring a dead structured layer.

## Five defects, each with a saved counterexample

1. **A report that contradicted itself.** The grounded-fact renderer rendered a
   metric only when coverage was `cited`, so a metric answered for one of two
   requested periods was reported as answered for neither: 关键发现 said
   `未取得可引用的原始披露事实` while 指标覆盖状态 said `部分已引用；已覆盖 2024`
   for the same four metrics, each carrying an evidence id and a footnote. The
   judge scored that report `0.0` on every dimension and the full gate was
   green.

2. **A summary promising figures the report did not have.** The boilerplate
   substituted for an unbindable summary points the reader at 关键发现; nothing
   checked that section had anything to point at.

3. **The live default could not say it was live.** `--live` selects `auto`,
   `auto` builds a routed provider, and that class declared no `fidelity`. The
   first live run recorded `structured_data: unknown` while AKShare was serving
   real records.

4. **Retrieval crashed when switched on.** The first live `RAG_ENABLED` arm died
   on its first sub-question — `EmptyRagSearchTool.search() got an unexpected
   keyword argument 'filter_query'` — and scored 0 of 3 cases. Three
   implementations of one call had drifted apart behind an `object` annotation.
   The flag being off by default is why this survived every gate.

5. **One published figure stated thirteen times.** A coverage line ran to 1,500
   characters holding every matching evidence id.

Defects 3, 4 and 5 were only reachable *because* the round ran live and turned
the dark flags on. None of them could have been found by any offline gate.

## What the dark flags were, and were not, decided on

No `content_affecting` flag was promoted. The reasons are per-flag and
recorded rather than averaged away:

- `PRIOR_MEMORY`, `PROCEDURAL_MEMORY` — **unmeasurable on this instrument**, not
  measured-and-unhelpful. The golden runner gives every question a fresh store,
  and both capabilities read what earlier runs wrote, so each is inert by
  construction. Pinned by `test_memory_flags_need_a_prior_run`. Deciding them
  needs a repeated-question experiment this round did not run.
- `RAG` — the golden runner constructs no retrieval service, so
  `capability_setup` falls back to the pre-index implementation and the flag can
  only add an empty-result degradation (`rag_search: 'fixture'`,
  `reason: not_found`). Its crash is fixed; its value remains unmeasured.
- The remaining five ran as live A/B arms. Six of eight arms outscored the
  control, four of them by 0.14–0.35 — and none of that is evidence.

## Why the A/B decided nothing, measured

Eight arms, three frozen questions, one judge sample each:

```
Q01: n=8 min=0.260 max=0.765 spread=0.505
Q02: n=8 min=0.015 max=0.963 spread=0.948
Q03: n=8 min=0.000 max=0.925 spread=0.925
between-arm spread of avg_weighted_score: 0.408
within-question spread (max):             0.948
ratio within/between:                     2.32
```

The spread on a single frozen question is **more than twice** the spread between
arms. Q02 scored `0.015` under one flag and `0.963` under another, on the same
question, the same gold answers and the same code. At this sample size the
instrument cannot separate a capability's effect from the retrieval lottery, so
no promotion is supportable in either direction, and none was made.

What would make it decidable: all 30 questions, ≥3 judge samples, arms run
sequentially rather than concurrently. Measured cost is ~CNY 0.4 per
3-question arm, so a full 30-question arm is ~CNY 4 and nine arms about CNY 36.

## The defect this round diagnosed and did not fix

A filing this agent downloaded, opened and read still reached the reader as
`未取得可引用的原始披露事实`. The chain, measured end to end:

1. the web PDF fetch produces `table_index=[]` and `bbox_index=[]`;
2. the extracted text is column-major — every row label first, then every value;
3. `_eligible_annual_report` refuses the source (cninfo serves it as
   `1223421172.PDF` under `web_fetch_pdf`), and even when forced eligible the
   one-line `label value value rate value` row shape cannot exist in that dump;
4. so the LLM extractor is the only path, and its excerpt for a table cell is
   the bare digit string `27,244,616,815.27`;
5. `_numeric_fields_are_extract_grounded` requires the metric name to appear in
   that excerpt, so the evidence supports nothing and the metric degrades to a
   gap.

Widening the excerpt window is **not** the fix: the window that reaches the
label reaches every other label too, which would let the guard bind any value to
any metric. The label-to-value association is destroyed upstream, in PDF text
extraction. An eligibility-only change was written, measured to close nothing on
its own, and reverted rather than shipped on the appearance of progress.

This is the next round's first target.
