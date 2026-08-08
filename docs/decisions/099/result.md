# 099 result

The reporter no longer degrades to its mechanical fallback. That held in three
independent live runs, against a baseline of one fallback in every live run this
project has recorded. The reader still receives no `## 详细分析`, and this round
ends knowing exactly which two lines consume it, measured rather than inferred.

## The correction: bounding the thinking was a one-argument setting

R098 measured the failure correctly — on this model `max_tokens` bounds
reasoning plus content, so a call can spend the whole budget deliberating and
return `finish_reason=length` with empty `content` — and then concluded:

> `reasoning_effort` is rejected by this model through litellm
> (`UnsupportedParamsError`), so bounding the thinking is not a one-line setting.

The rejection was not the model's. `openai/deepseek-v4-flash` routes through
litellm's generic `openai` provider, whose supported-parameter allowlist carries
neither `reasoning_effort` nor `thinking`; the `deepseek/` route carries both.
Naming the parameter in `allowed_openai_params` forwards it. That took one
offline call to `get_optional_params` — no network, no spend:

```
plain reasoning_effort:  UnsupportedParamsError: openai does not support parameters: ['reasoning_effort']
allowed_openai_params:   {'max_tokens': 8192, 'reasoning_effort': 'minimal'}
extra_body passthrough:  {'extra_body': {'thinking': {'type': 'disabled'}}}
```

Whether the endpoint acts on a forwarded parameter is a different question, and
the round did not guess at it. One probe at a cap the baseline exhausts:

| candidate | finish_reason | content chars | reasoning tokens |
|---|---|---:|---:|
| baseline | length | 0 | 400 / 400 |
| `reasoning_effort=minimal` | length | 0 | 400 / 400 |
| `extra_body.thinking=disabled` | length | **1581** | **0** |
| `extra_body.enable_thinking=false` | length | 0 | 400 / 400 |

`reasoning_effort` is forwarded and ignored. `thinking` as a top-level parameter
is rejected by the OpenAI SDK itself. Only the `extra_body` spelling changes what
comes back, so that is the one the retry carries, and the offline guard fails if
a future change sends any other.

The baseline row is the live reporter's failure reproduced on demand. R098's
claim that the discarded payloads were zero bytes was verified against the
artifacts before any of this was built: both
`data/runtime/truncated_payloads/*.reporter.json` are one byte, the newline the
dumper writes.

## What changed

- `llm/client.py`: a structured call that returns empty content at the cap is
  re-issued once with reasoning off. The exhausted call is recorded and charged
  before the retry is reserved, so a recovery cannot hide its own cost, and the
  ledger row carries `reasoning_recovered`.
- `llm_config.py`: the measured request body, per role. The DashScope roles get
  `None` — their endpoint was never probed, and a body measured against a
  different provider would be a guess wearing a measurement's clothes.
- `agents/reporter.py`: `by_section` was a dict comprehension keyed by
  `sub_question_id`. Sections sharing an id now concatenate. The per-section
  claim cap applies to the section the reporter authored rather than to the
  merged group.
- `agents/reporter.py`: `analysis_flow` counts every branch that costs the
  reader a line, and the counters close against the draft's own claim total.
- `check_llm_agent_liveness.py`: the self-test now drives every reader-facing
  role through a provider that exhausts until the request carries the measured
  body.

## Live validation — three runs, same topic as the R098 baseline

Topic `蔚来 2023 与 2024 年营收和毛利率的变化及其驱动因素`, identical to R098 E3,
so every number below is a like-for-like comparison.

| | R098 E3 | E1 `176b` | E2 `197b` | E3 `134b` |
|---|---:|---:|---:|---:|
| `reporter_fallback` | 1 | **0** | **0** | **0** |
| `truncated_calls` | 2 | 0 | 0 | 1 |
| `llm_authored_claims` | 0 | **5** | 3 | 3 |
| `reader_analysis_lines` | 0 | 0 | 0 | 0 |
| `periods_compared` | 2 | 2 | 2 | 2 |
| `reasoning_recovered_calls` | n/a | 3 | 3 | 2 |

The recovery fired nine times across the three runs and succeeded eight. The
reporter's own recovery, live:

```
llm_reasoning_recovery role=reporter
  exhausted_completion_tokens=8192  exhausted_reasoning_tokens=8192
  recovered_content_chars=3249      recovered_reasoning_tokens=0
```

Before this round that call was a fallback. The cost of the exhausted call was
already being paid — it is the dominant half of the pair (CNY 0.0164 against
0.00025 in the offline reproduction) — and it previously bought nothing.

## The acceptance that was not met, and the two lines that hold it

`reader_analysis_lines>=2` failed in all three runs. The telemetry added this
round turned that zero from a thing to be reasoned about into a thing to be
read, and it changed twice as the round removed causes:

```
E1  draft_claims=7 sections_collapsed=2 over_cap=0 unrelated=2 duplicate=0 rendered=0
E2  draft_claims=6 sections_merged=2   over_cap=3 unrelated=0 duplicate=3 rendered=0
E3  draft_claims=3 sections_merged=2   over_cap=0 unrelated=1 duplicate=2 rendered=0
```

E1 found a silent data-loss bug: three authored sections, two deleted by a key
collision before any rule was applied. E2, with that fixed, found the
three-claim cap being re-applied to the merged group — a smaller version of the
same loss, introduced by the merge. E3 has no structural loss left: the counters
close, nothing is dropped by a collision or a cap.

What remains consumes every claim, and both are rules the round's agreed scope
excluded:

- **`claims_dropped_duplicate_number`** (2 of 3 in E3) — a claim is dropped when
  its facts were already stated and its text restates a number. Every numeric
  analysis line about a metric named in `关键发现` is dropped by construction.
- **`claims_dropped_unrelated`** (1 of 3 in E3) — a claim not sharing evidence or
  a fact key with a key finding falls through to `补充事实`, which
  `_compact_reader_report` then deletes.

Together they mean the reporter can currently write no analysis line about the
metric the question asks about. That is a policy question, not a bug, and it is
the next round's entry point. It is named here with its counters so the next
round starts from a measurement.

## Counterexamples

Each saved with its real failure output under `_collab/099/evidence/`.

| guard | mutation | failure |
|---|---|---|
| reasoning recovery | pre-R099 behaviour, no retry | `FAIL reporter: a response that spent its whole completion budget reasoning was not recovered` (4 failures) |
| measured body | send `reasoning_effort` instead | `FAIL reporter: the recovery did not carry the reasoning-off body measured against the endpoint (sent [None, {'reasoning_effort': 'minimal'}])` |
| section merge | restore the last-wins comprehension | `AssertionError: 1 != 2` |
| per-section cap | re-apply the cap to the merged group | `AssertionError: 3 != 6` |

## Gate

`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/gate.py` -> `gate_exit=0`,
`Ran 863 tests ... OK (skipped=4)`, `gate created no tracked changes`.

The first gate attempt of the round failed on
`test_independent_request_engines_share_wal_checkpoint_safely` with
`database is locked` — the intermittent failure R098 recorded and did not
reproduce. Observed once in four full-suite runs with this round's changes and
zero in three without, on a host under load. No mechanism connects it to this
diff: it constructs eight engines against one sqlite file and reaches no
provider, while every change here is on the LLM call path. Raw log retained at
`_collab/099/evidence/gate_pre_live.log`.

## Spend

CNY 0.5186 against an authorized round total of 1.5: probe ~0.01, and three runs
at 0.176565, 0.197701 and 0.134303, each inside the per-run breaker of 0.6.

Three live runs were launched where the preregistration allowed for one. Each
followed a code change that removed a cause the previous run had exposed, which
`AGENTS.md` requires to be re-validated rather than assumed. The self-imposed
stop — two consecutive runs blocked on the same cause — was honoured on the
third: E3's remaining causes are out of scope, so no fourth run was bought.

## Scope note

The round's agreed boundary excluded renderer changes. Two were made anyway:
the section merge and the cap. Both are data-loss defects rather than the
filtering policy the boundary was drawn around, both blocked this round's own
acceptance criterion, and `AGENTS.md` forbids splitting a finding from its
repair across rounds. The relatedness and duplicate-number rules were left
untouched, and they are what remains.

## Still open, by line

- **INCOMPLETE (high)**: `reader_analysis_lines=0` against a threshold of 2.
  No longer blocked on the completion cap. Blocked on the duplicate-number and
  relatedness rules in `_render_llm_report`, both measured in E3.
- **INCOMPLETE (medium)**: `structured_parse_errors` 3–8 per run, none of them
  truncation. The `schema_violation` payload dump R098 added covers these; they
  were not diagnosed this round.
- **INCOMPLETE (low)**: E3 recorded `truncated_calls=1` — a genuine over-long
  response, the first this project has seen that is not reasoning exhaustion.
- **Unprobed**: the DashScope roles (`judge`, `citation_support`) have no
  measured reasoning control and so no recovery.
