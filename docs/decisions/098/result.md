# 098 result

Both commissioned live validations executed. The multi-period one produced the
project's first report that states both requested periods' revenue with
citations. Neither met its full acceptance, and the reason turned out not to be
the one two rounds of cap analysis had assumed.

## The finding: the completion cap is spent thinking, not writing

R090 diagnosed a 1024-token cap that could not hold the extractor's and
reporter's JSON, raised it, and the roles kept truncating. R092 bounded the
extractor schema. R097's live run truncated the reporter at 8192 tokens, its
salvage found nothing complete, and the reader received a 22-line report with
zero authored analysis lines.

This round kept the discarded payload. It was **zero bytes**, twice, in two
independent runs. A direct provider probe explains it:

```
finish_reason = length
message keys  = [..., 'content', 'reasoning_content', ...]
content       = ''
reasoning_content len = 926
usage.completion_tokens_details = {"reasoning_tokens": 200}   # of 200
```

The configured model is a reasoning model and `max_tokens` bounds reasoning
**plus** content. The failing calls did not write too much JSON; they spent the
whole budget thinking and never began the JSON. The ledger recorded only
`completion_tokens` and `finish_reason`, so that response has been
indistinguishable from an over-long one for every round that looked at it — the
same shape of blindness R090 found in `parse_error` being a bare boolean, one
level up.

`reasoning_effort` is rejected by this model through litellm
(`UnsupportedParamsError`), so bounding the thinking is not a one-line setting.
Naming and measuring the failure is what this round delivers; making it
recoverable is the next round's entry point.

## Live validation E1 — the R097 multi-period run

`artifacts/097/live-nio-multiperiod`, source commit `74f9153`, CNY 0.159086.

```
extractor_fallback=0 reporter_fallback=1 structured_parse_errors=4
truncated_calls=4 llm_authored_claims=0 reader_analysis_lines=0
orphan_footnotes=4 periods_compared=2 cross_source_domains=1
```

`periods_compared=2` — the first time in this project's history, against a
baseline of 1 in every stored package. The R097 planner-prompt change works.

Everything else failed, all downstream of one truncated reporter call. What the
reader received: 22 lines, both `关键发现` bullets apologies with no numbers and
no citations, and 4 of 5 references cited by nothing. `cross_source_domains=1`
was a rendering loss rather than a retrieval one — the run's 10 evidence items
span `www.sec.gov` (8) and `www.itiger.com` (2).

## Live validation E2 — the A-share path, first execution ever

`artifacts/098/live-ashare-moutai`, source commit `94487ff`, CNY 0.070160,
topic `贵州茅台（600519）2023 与 2024 年营业收入和毛利率的变化及其驱动因素`.

```
extractor_fallback=0 reporter_fallback=0 structured_parse_errors=1
truncated_calls=1 llm_authored_claims=3 reader_analysis_lines=0
orphan_footnotes=0 periods_compared=2 cross_source_domains=1
```

The planner did its part: two `financial_indicators` requests for symbol
`600519`, periods `["20231231","20241231"]`, metrics 营业收入 and 主营业务毛利率.
Both failed:

```
structured_data_stats.values.execution_failures = 2
"AKShare financial_indicators failed: timeout after 15.000s"
provider_usage = {"search": 3, "structured_data": 0, "disclosure": 1,
                  "rag_search": 1, "llm": 1}
```

The run retrieved 2 sources and 0 structured records, and delivered a report
whose only revenue coverage reads `已覆盖 2020，缺少 2023, 2024`, resting on a
single 2021 broker PDF. It is not silent — `风险与限制` states the gap plainly —
but the path yields no usable research.

**The timeout was ours, not AKShare's.** AKShare answers the same request in
4.7s and returns the `20231231` and `20241231` columns. A multiprocessing queue
is a pipe with a bounded buffer: a child returning more than the buffer holds
blocks inside `put` until the parent reads, and the parent was blocked in `join`
waiting for that same child to exit. Each waited on the other until the timeout,
on every attempt, for every result too large for the pipe.
`stock_financial_abstract` for 600519 returns an 80x104 frame, so the A-share
structured path deadlocked deterministically and **had never once succeeded**.
Fixed; the same call now returns both periods in 5.6s.

## Live validation E3 — the multi-period topic on the bounded schemas

`artifacts/098/live-nio-multiperiod-fixed`, source commit `94487ff`, CNY 0.166909.

```
extractor_fallback=0 reporter_fallback=1 structured_parse_errors=6
truncated_calls=2 llm_authored_claims=0 reader_analysis_lines=0
orphan_footnotes=4 periods_compared=2 cross_source_domains=3
```

`cross_source_domains` 1 -> 3. The reader now gets both periods with citations:

> 营业收入（请求报告期：2023, 2024）：蔚来 2024 …657.3 亿元 [^1]；蔚来 2023年 …556.179 亿元 [^2]；…

That is the first delivery this project has produced that answers a question
about change with both periods' figures cited.

The reporter still fell back, for the reasoning-exhaustion reason above, so
`reader_analysis_lines` is still 0. The schema bounds this round added did not
fix it and were not aimed at the real cause; they also introduced 4
`schema_violation` parse errors, 2 of which self-repaired. They are kept because
an unbounded structured contract is a real defect and the guard that catches it
is real — but they are not the fix, and the round does not claim they are.

## Changes

- `schemas.py`: bound every field of `ReportDraft`, which declared no
  `maxLength` and no `maxItems` on anything, and the `ExtractedClaim` fields
  R092 left open. `MAX_EXTRACTED_CLAIMS` 12 -> 8 so the worst case fits the cap.
- `check_llm_agent_liveness.py`: the hand-written extractor worst case supplied
  invented lengths for unbounded fields, so it reported a finite worst case for
  a schema that had none. Replaced by a walker that refuses and names the
  field, run for every reader-facing role.
- `llm/client.py`: record `reasoning_tokens` and `content_chars`; classify an
  empty completion at the cap as `reasoning_exhausted` rather than `truncated`;
  aggregate `reasoning_exhausted_calls`; keep the payload that overran, and the
  payload that violated a bound.
- `akshare_structured_data.py`: read the child's result before waiting for it
  to exit.

## Counterexamples

Each saved with its real failure output under `_collab/098/evidence/`.

| guard | mutation | failure |
|---|---|---|
| unbounded schema | remove `ReportDraft.summary`'s bound | `FAIL reporter: ReportDraft.summary declares no maxLength` |
| worst case vs cap | permit 12 analysis sections | `FAIL the reporter schema permits ~15029 tokens, which its 8192-token cap cannot hold` |
| queue deadlock | the pre-R098 join-then-read order | `AKShareStructuredDataError: AKShare probe failed: timeout after 20.000s` |
| reasoning exhaustion | force the classifier to False | `AssertionError: 'truncated' != 'reasoning_exhausted'` |

## Gate

`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/gate.py` -> `gate_exit=0`,
`Ran 854 tests ... OK (skipped=4)`, `gate created no tracked changes`.

## Environment: a second heavyweight-import stall, measured

E2 attempts 2 and 3 hung before `run_started` with near-zero CPU and ignored
`SIGINT`. `-X faulthandler` + `SIGABRT` named it: `import akshare`
(`akshare/__init__.py:3433`), reached from
`build_engine_capability_registry` during `DeepResearchEngine.__init__`.

| import | wall | CPU |
|---|---:|---:|
| cold | 9:15.92 | 1.36s (0%) |
| warm | 1.65s | 0.59s |

Same pathology R090 recorded for `import litellm`, in a second place, and hit at
engine construction on every live run using the live structured provider — which
`_configure_mode` makes the default. Warming it once made both runs start in
3 seconds.

E2 attempt 1 was a command-construction error of mine (missing `PYTHONPATH=src`),
zero provider calls, log retained.

## Spend

CNY 0.237068 across the two runs this round launched, both inside the
authorized per-run breaker of CNY 0.6. E1 was inherited from R097 at CNY 0.159086.

## Still open, by line

- **INCOMPLETE (high)**: `reader_analysis_lines=0` against a threshold of 2, in
  all three runs. Blocked on reasoning exhaustion, not on the renderer.
  `reasoning_effort` is unsupported for this model through litellm; the
  candidates are a larger cap for structured roles, a non-thinking model
  variant, or a retry that limits thinking. None is validated.
- **INCOMPLETE (high)**: E3's `关键发现` states
  `NIO Inc. 2023年 年度营业收入为167,180,000 CNY` beside `2023年 …556.179 亿元`
  in the next section — two 2023 revenue figures differing by ~333x, in one
  report. The structured record is
  `{"data_source": "SEC EDGAR Company Facts", "dimension": "年度",
  "period": "2023-12-31", "unit": "CNY", "value": "167180000"}`. Candidate
  cause, **not verified**: `sec_companyfacts.py:288-303` filters facts by
  `end` and `fy` but never by the fact's `start`, so a sub-annual duration can
  be emitted as an annual value; 167.18亿 is close to the Q4-2023 figure the
  report's own footnote 2 carries (171 亿元). This is a downstream path that
  could not show itself until multi-period retrieval worked.
- **INCOMPLETE (medium)**: the reader-visible contradiction between
  `disclosure_policy.py:94` (`未取得可引用的原始披露事实`) and
  `reporter.py:1227` (`部分已引用；已覆盖 …`), present in E1 and E2. Two
  renderers, two definitions of "covered".
- **INCOMPLETE (medium)**: 4 new `schema_violation` parse errors introduced by
  this round's bounds. The payload dump now covers schema violations, so the
  next round can tune the bounds from the responses rather than guess.
- **INCOMPLETE (medium)**: `orphan_footnotes=4` whenever the reporter falls
  back; references are still built from the evidence store rather than from
  what the body cites.
- **Not reproduced this round**: the intermittent
  `test_independent_request_engines_share_wal_checkpoint_safely`
  `database is locked` failure. 854 tests passed in the one full gate run.

## Note on this round's own method

The schema-bounds commit was written before the payload dump existed, from
token counts alone, and it aimed at the wrong cause. The dump that corrected it
cost about fifteen lines. Where a measurement is cheap and the inference from
existing telemetry is not forced, take the measurement first — R090 and R092
both spent a round each on the same inference.
