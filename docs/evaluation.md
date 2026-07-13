# Evaluation Harness

The harness treats evaluation as a first-class subsystem, not a screenshot.

## Metrics

- `task_success_rate`: report generated with at least one evidence record
- `citation_accuracy`: in deterministic mode, citation markers in bullet claims map to Evidence rows and the cited claim has deterministic text overlap with `Evidence.claim` or `Evidence.extract_text`; in LLM mode this is `null` with a reason because paraphrase-aware judging is not implemented yet
- `citation_resolution_rate`: citation markers that resolve to real Evidence rows, computed in both deterministic and LLM modes
- `citation_repair_retry_rate`: Golden Set mechanical metric equal to the share of runs where Reporter performed one structured evidence-id repair retry before rendering
- `uncited_claim_rate`: Golden Set mechanical metric equal to uncited rendered ReportClaims divided by all rendered ReportClaims
- `critic_catch_rate`: MVP heuristic/proxy for whether the Critic exposed quality issues. Current deterministic logic scores visible issue coverage, using `min(1.0, len(issues) / 3)` when issues are present and `1.0` when no issues are found. It is not true seeded issue recall or human-labeled Critic recall.
- `answer_relevance`: topic terms appear in the final report
- `faithfulness`: bullet claims in the report carry citations
- `cost_usd`, `cost_cny`, `latency_seconds`, `token_used`, `price_source`: operational metrics for Pareto analysis. LLM mode accounts natively in CNY from the LiteLLM ledger.

Unsupported or invalid bullet citations are counted as `citation_error` bad cases in deterministic scoring. Golden Set LLM rounds additionally run a judge-backed `citation_support_rate` over extracted report claims and evidence.

Production version: compute true critic recall from seeded issues or manually labeled bad cases.

## Golden Set v1

Golden Set v1 is frozen under `data/golden_set/v1/` with release version `v1.1`.
It contains 30 finance-oriented cases across 财报解读, 对比研究, 行业研究,
and 事件时间线. The frozen set records gold facts, source references, the
quarantine list, freeze-time adjustments, the evaluation `as_of`, recording
`as_of` distribution, and the frozen corpus fingerprint.

Frozen assets:

- `data/golden_set/v1/questions.json`: 30 cases with source-backed gold fields.
- `data/golden_set/v1/freeze.md`: v1.1 freeze note and complete revision log.
- `data/golden_set/v1/revisions_v11.json`: machine-readable old/new values, source excerpts, and four-key contracts.
- `data/golden_set/v1/audit_v11.md`: 79-slot entity/metric/period/scope-unit/numeric audit.
- `data/golden_set/v1/results/g1_judge_v11.json`: G1 saved-state rejudge on release gold v1.1.
- `data/golden_set/v1/results/g2_judge_v11.json`: G2 saved-state rejudge on release gold v1.1.
- `data/golden_set/v1/results/g3_judge_v11.json`: G3 saved-state rejudge on release gold v1.1.
- `data/golden_set/v1/results/v11_three_point_comparison.md`: official per-dimension and per-question v1.1 table with v1.0 history beside it.
- `data/golden_set/v1/results/round1.json`: first full judge round.
- `data/golden_set/v1/results/round2.json`: second full judge round.
- `data/golden_set/v1/results/round_diff.json`: round two minus round one metrics.
- `data/golden_set/v1/results/judge_calibration.json`: archived judge-model calibration sample.
- `data/golden_set/v1/results/g1_rejudge_qwen37.json`: G1 saved-state rejudge with the current locked judge.
- `data/golden_set/v1/results/gen2_judge1.json`: G2 judge round with the current locked judge.
- `data/golden_set/v1/results/g1_qwen37_vs_gen2.json`: formal same-judge G1/G2 comparison.
- `data/golden_set/v1/results/gen3_judge1.json`: G3 judge round after citation repair retry replaced renderer backfill.
- `data/golden_set/v1/results/judge_calibration_qwen37_vs_qwenmax.json`: current 10-case judge calibration sample.

Golden Set v1.1 evaluation `as_of` is `2026-07-12`. The frozen corpus contains
486 canonical recording files, 694 source rows, 510 unique source URLs, and
fingerprint `ef2d1fd2c414502140162508ef32838aaf8e4a56a6ab3678f9f57ed04f86960e`.
No cases are quarantined. The independent `data/recordings/gold_appendix/`
used eight bounded Tavily basic credits and does not change the frozen-corpus
fingerprint. AKShare live remains outside the freeze because the network and
geography path is unavailable; recorded fixture data remains the validation
boundary.

Run the current round runner against saved states or replay search:

```bash
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/run_golden_round.py \
  --questions data/golden_set/v1/questions.json \
  --output data/golden_set/v1/results/g1_judge_v11.json \
  --work-dir _collab/008a_gold-v11/g1_rejudge \
  --round-id g1-judge-v11 \
  --generation G1 \
  --as-of 2026-07-12 \
  --ledger-path _collab/008a_gold-v11/judge_v11_ledger.jsonl \
  --judge-samples 3 \
  --state-path-map _collab/006v_judge-verdict/g1_state_path_map.json
```

`--state-path-map` re-scores saved `ResearchState` artifacts without rerunning
Planner, Extractor, Reporter, or search. Omit it to run the full LLM pipeline
over frozen-corpus replay; that path is significantly slower for evidence-heavy
cases.

Generation passes and judge passes are separate units:

- A generation pass reruns Planner, Researcher replay, Extractor, Reporter, and
  Evaluator to produce new `ResearchState` and report artifacts.
- A judge pass scores an existing or newly generated report with the configured
  judge model and citation-support verifier.
- The historical `round1` and `round2` assets are two judge passes over the same
  generation pass. They are therefore a test-retest reliability check, not a
  repair-loop before/after comparison. The observed composite movement was
  `+0.0043`, which is treated as test-retest noise within the `±0.01` band.

## Golden Production Four-Key Gate

The v1.1 rebuild fixes a Golden production-line defect rather than a research
workflow defect. In v1.0, source selection, extraction/refill, and freeze review
all accepted the same unsafe premise: a plausible excerpt was treated as a
valid slot value without proving that the value matched the slot definition.
That shared premise penetrated all three defenses and produced 19 confirmed
defects across entity, normalized metric, report period, and scope/unit.

`scripts/audit_gold.py` is now a permanent positive and release control. It
normalizes finance metrics with `data/finance_metric_normalization.json`, parses
annual, quarterly, half-year, first-three-quarter, range, and event periods,
checks entity plus scope/unit, and requires every declared numeric token to
occur in the source excerpt. Running it on v1.0 reproduced the exact 19-defect
007S2/PM list; v1.1 reports 76 PASS, zero DEFECT, and only the three explicitly
annotated PM UNCERTAIN slots Q04s3, Q13s3, and Q20s1.

`scripts/refill_gold.py` calls the same gate before writing. It also rejects
stale old values, edits outside the prompt-authorized slot set, and shared facts
whose value or source diverges. This makes the audit contract a write-time
invariant instead of a post-freeze review convention.

Golden Set score interpretation uses two separate noise bands:

- Judge test-retest noise: use `±0.01` as the operating band. The observed
  same-generation retest movement was `±0.004`, so smaller composite changes
  must not be described as product improvement or regression.
- Cross-generation noise: with `n=30`, the composite-score standard error is
  approximately `0.037`, and individual questions can move by up to about
  `±0.4`. G1/G2/G3 generation comparisons are useful directional diagnostics,
  but composite deltas at this scale are statistically hard to separate from
  generation variance without more samples or paired human review.

## Judge

Golden Set judge calls use the unified `LLMClient` with role `judge`; citation
support uses role `citation_support`. Both roles are locked in `llm_config` to
`openai/qwen3.7-plus` through DashScope's OpenAI-compatible endpoint. Each full
round uses three judge samples per question and aggregates dimensions by median.
The locked scoring dimensions and weights are:

| Dimension | Weight |
| --- | ---: |
| `fact_coverage` | 0.35 |
| `fact_accuracy` | 0.25 |
| `citation_support` | 0.25 |
| `synthesis_balance` | 0.15 |

Prompt file: `prompts/judge.md`. Current prompt hash:
`2e87f85cb54673ab6f84e0f0fc4b8c108441757e20ecd9ec4c3416df5d893533`.

The archived judge-model calibration sample over Q01-Q10 used an earlier judge
version and produced dimension agreement rate <=0.1 of `0.4`, average dimension
absolute difference `0.3299`, and average weighted-score absolute difference
`0.3362`. It remains a historical judge-sensitivity signal, not the current
routing contract.

The current Q01-Q10 calibration on G2 saved states compares `openai/qwen3.7-plus`
against `openai/qwen-max`, one sample each. Signed average differences are
reported as qwen3.7-plus minus qwen-max:

| Dimension | Signed Avg Diff |
| --- | ---: |
| fact coverage | -0.1573 |
| fact accuracy | -0.1087 |
| citation support | -0.0260 |
| synthesis balance | -0.1100 |
| weighted score | -0.1052 |

On this sample, qwen3.7-plus is materially stricter than qwen-max. PM review is
still required before treating Golden Set scores as stable product benchmarks.

## Golden Set v1.1 Release Results

The release series rejudges the unchanged G1, G2, and G3 saved states against
gold v1.1. Each generation contains all 30 effective cases, uses three judge
samples aggregated by median, reruns the citation_support verifier, and has zero
structured failures. Per-generation research ids are identical to the v1.0
rounds. Therefore no Planner, Researcher, Extractor, Reporter, Critic, report,
or evidence change enters this comparison; the only intentional input change is
the gold revision manifest. Judge sampling remains a test-retest noise source.

| Metric | G1 v1.1 | G2 v1.1 | G3 v1.1 |
| --- | ---: | ---: | ---: |
| avg weighted score | 0.8337 | 0.7714 | 0.7982 |
| avg fact coverage | 0.7867 | 0.6707 | 0.7090 |
| avg fact accuracy | 0.8817 | 0.8700 | 0.8867 |
| avg citation support | 0.8720 | 0.8487 | 0.8667 |
| avg synthesis balance | 0.8000 | 0.7133 | 0.7450 |
| avg citation support rate | 0.8883 | 0.7227 | 0.7640 |
| avg citation resolution rate | 0.6000 | 1.0000 | 0.9333 |
| avg citation repair retry rate | 0.0000 | 0.0000 | 0.5333 |
| avg uncited claim rate | 0.0000 | 0.0000 | 0.0779 |

The official side-by-side v1.0/v1.1 dimension table and all 30 per-question
rows are generated in
`data/golden_set/v1/results/v11_three_point_comparison.md`. Composite deltas
versus historical v1.0 are `+0.0338`, `+0.0300`, and `+0.0179` for G1, G2, and
G3. These are gold-version movements, not new product-generation results, and
remain subject to the documented cross-generation and judge test-retest bands.

The two false-premise cases remain correctly refuted in all three saved
generations under v1.1 (`false_premise_failed=false`):

| Case | G1 weighted / citation rate | G2 weighted / citation rate | G3 weighted / citation rate | Behavior |
| --- | ---: | ---: | ---: | --- |
| Q08 | 0.7525 / 1.000 | 0.7575 / 0.833 | 0.8425 / 0.667 | refuted |
| Q16 | 0.8400 / 0.917 | 0.8875 / 1.000 | 0.8800 / 0.250 | refuted |

The three v1.1 judge rounds cost CNY `1.65913960`, `1.67774040`, and
`1.65709656`, respectively, for a combined CNY `4.99397656`. The shared task
ledger contains 271 judge rows and 91 citation_support rows; two additional
rows beyond the nominal 360 calls are recorded structured-repair attempts.

## Golden Set v1.0 Historical Results

All numbers in this section were measured on historical gold v1.0. Historical
`round1` and `round2` are same-generation test-retest judge passes
from the pre-006V judge identity. They are retained as historical assets only:

| Metric | G1 judge pass 1 | G1 judge pass 2 | Delta |
| --- | ---: | ---: | ---: |
| avg weighted score | 0.6134 | 0.6177 | +0.0043 |
| avg fact coverage | 0.6806 | 0.6749 | -0.0057 |
| avg fact accuracy | 0.5950 | 0.5922 | -0.0028 |
| avg citation support | 0.5589 | 0.5789 | +0.0200 |
| avg synthesis balance | 0.5783 | 0.5917 | +0.0134 |
| avg citation support rate | 0.8104 | 0.8256 | +0.0152 |
| avg citation resolution rate | 0.6000 | 0.6000 | +0.0000 |

Both false-premise cases, Q08 and Q16, were classified as refuted in both rounds.
No generation repair was applied between these two judge passes.

The following judge-effect decomposition was measured on gold v1.0. 006V
rejudged the G1 saved states with the current locked judge. That exposed
the G2 regression: the apparent historical improvement was a judge-identity
artifact. A useful decomposition is:

```text
0.6134 + 0.1865 - 0.0585 = 0.7414
```

Here `0.6134` is the historical G1 score under the earlier judge, `+0.1865` is
the judge-identity uplift observed by rejudging G1 as `0.7999`, and `-0.0585`
is the same-judge G2 regression. This is the canonical judge-effect example for
why Golden Set scores must be paired by judge identity.

On historical gold v1.0, 006F2 removed renderer lexical backfill and replaced
it with one structured Reporter repair retry that asks the model to add real
`evidence_ids` before rendering. The historical same-judge sequence was:

| Metric | G1 rejudge | G2 backfill | G3 repair retry |
| --- | ---: | ---: | ---: |
| avg weighted score | 0.7999 | 0.7414 | 0.7803 |
| avg fact coverage | 0.7577 | 0.6207 | 0.6827 |
| avg fact accuracy | 0.8400 | 0.8273 | 0.8423 |
| avg citation support | 0.8250 | 0.8483 | 0.8670 |
| avg synthesis balance | 0.7900 | 0.7017 | 0.7600 |
| avg citation support rate | 0.8062 | 0.7496 | 0.7761 |
| avg citation resolution rate | 0.6000 | 1.0000 | 0.9333 |
| avg citation repair retry rate | n/a | n/a | 0.5333 |
| avg uncited claim rate | n/a | n/a | 0.0779 |

Under the cross-generation noise band, G3's composite score is statistically
not distinguishable from the G1 rejudge baseline. The reliable conclusion is
narrower: G3 restored true citation-resolution measurement, removed renderer
backfill, and recovered most of the G2 regression without changing gold values,
judge prompts, scoring weights, or graph architecture.

Bad-case category counts across the same-judge sequence:

| Category | G1 | G2 | G3 |
| --- | ---: | ---: | ---: |
| 事实错误 | 6 | 10 | 8 |
| 引用不支持 | 15 | 16 | 17 |
| 检索不全 | 14 | 18 | 17 |
| 结构或平衡缺失 | 9 | 13 | 11 |

The G1 citation-resolution anomaly was a pipeline defect: LLM Reporter drafts
could omit `evidence_ids` for `ReportClaim` objects, and the renderer previously
allowed uncited bullet claims to reach the final report. The G2 fix correctly
strengthened Reporter prompt discipline but incorrectly used renderer lexical
backfill, producing a misleading mechanical resolution rate and a high
`backfilled_citation_rate`. G3 removes lexical backfill: claims still lacking
valid evidence ids after the repair retry render uncited, so
`citation_resolution_rate` is again a real measurement rather than a renderer
artifact. No gold values, judge prompts, scoring weights, or graph architecture
were changed.

## Golden Recording Controls

Golden Set live recording uses the search recording layer in `record` mode and
requires an explicit `DEEPRESEARCH_AS_OF`; the recording metadata uses that
runtime value as the single as-of source. Tavily read timeout defaults to 60
seconds, failed individual queries are recorded as partial instead of aborting
the run, and existing recording keys are replayed idempotently on rerun. Each
run stops issuing additional searches after `DEEPRESEARCH_MAX_SEARCHES_PER_RUN`
(default `20`). Tavily `raw_content` is capped per source by
`DEEPRESEARCH_TAVILY_RAW_CONTENT_CHAR_LIMIT` (default `40000` characters) before
extraction.

Before a new live recording round, rotate `data/runtime/search_ledger.jsonl` to
the task collaboration directory and start a fresh runtime ledger. Tavily credit
guardrails are scoped to the current ledger file, not to all historical runs.
Only rows that actually attempted a Tavily API call count toward credit usage.
Rows refused by the guardrail are written with `refused=true` and
`credit_estimate=0`. The warning and hard-stop thresholds are configurable via
`DEEPRESEARCH_TAVILY_CREDIT_WARNING_THRESHOLD` and
`DEEPRESEARCH_TAVILY_CREDIT_HARD_THRESHOLD`; evaluation recording currently uses
450 and 520.

Recording `as_of` and evaluation `as_of` are separate facts. Recording `as_of`
is provenance metadata for when a source key was collected and may have multiple
values inside one frozen corpus. Evaluation `as_of` is a single run-level date
injected through `DEEPRESEARCH_AS_OF`; for Golden Set v1.1 it is `2026-07-12`
and controls freshness-sensitive rules. The unchanged frozen corpus separately
retains recording dates `2026-07-08` and `2026-07-09`.

## Frozen Corpus Replay

Exact-key replay was retired for Golden Set evaluation. The prior design keyed
recordings by the literal LLM-generated query, `top_k`, and `source_type`, but
temperature-zero LLM planning still produced byte-level query drift across runs.
That made otherwise valid recorded corpora fail replay with exact-key misses.

Replay mode now treats `data/recordings/golden_v1/` as a frozen corpus. It loads
all recorded sources with non-empty content, excludes zero-source recordings,
and ranks sources for any incoming query with deterministic lexical overlap over
title and body. `source_type` is respected first; if the filtered set has no
candidate, replay falls back to all source types. Replay mode does not call
external search services and does not write the recording directory.

This is a deterministic evaluation mechanism, not a claim that Tavily would
return the same ordering live. Frozen-corpus results are bounded by corpus
coverage and lexical ranking quality. Each freeze records the runtime `as_of`
date and a directory content hash so score changes can be tied to a specific
corpus snapshot.

## Golden Questions

`data/eval_set_deterministic.jsonl` contains 50 deterministic CI regression cases covering financial AI, wealth management, citation verification, Evidence Store design, Critic loops, checkpointing, Docker deployment, and interview packaging.

Run:

```bash
PYTHONPATH=src .venv/bin/python scripts/run_eval.py --limit 5
```

The command writes `artifacts/evaluation/latest_metrics.json`.

## Metric Diff

`data/eval_baseline.json` stores the deterministic MVP baseline for a 5-case
local sweep. Compare a new run against it with:

```bash
PYTHONPATH=src .venv/bin/python scripts/run_eval.py --limit 5 --compare-baseline
```

Use a custom baseline path when validating an experiment:

```bash
PYTHONPATH=src .venv/bin/python scripts/run_eval.py --limit 5 --compare-baseline --baseline-path artifacts/evaluation/latest_metrics.json
```

The comparison gates quality regressions for `avg_citation_accuracy`,
`avg_citation_resolution_rate`, `avg_faithfulness`, `avg_critic_catch_rate`, and total bad-case count.
`avg_cost_usd`, `avg_latency_seconds`, and `avg_token_used` are reported as
operational diffs; latency changes are informational so local machine variance
does not fail the smoke check.

## Current Deterministic Baseline

Task 8 packaging validation uses the repo-local Python 3.12 environment and the
deterministic fixture path. It does not require external LLM/search keys.

- Tests: full `unittest` suite passes
- Demo: `phase=done status=done`
- Demo artifact: `artifacts/demo_report.md`
- Checkpoint demo: `paused_phase=critiquing paused_status=paused`, then `resumed_phase=done resumed_status=done`

Deterministic evaluation sweep: `PYTHONPATH=src .venv/bin/python scripts/run_eval.py --limit 5 --compare-baseline`

| Metric | Value |
| --- | ---: |
| `cases` | `5` |
| `avg_task_success_rate` | `1.0` |
| `avg_citation_accuracy` | `1.0` |
| `avg_citation_resolution_rate` | `1.0` |
| `avg_critic_catch_rate` | `0.8` |
| `avg_answer_relevance` | `1.0` |
| `avg_faithfulness` | `0.923` |
| `avg_cost_usd` | `0.023` |
| `avg_token_used` | `9644.8` |
| `bad_case_categories.numeric_conflict` | `6` |

The baseline comparison status is `pass`. Latency is reported as an
informational operational diff because it varies by local machine.

This is a deterministic local fixture run for Gate 4 review, not a production LLM/search benchmark. It does not imply Tavily, LiteLLM, Postgres, or LangGraph production integrations are complete.

## Bad Case Categories

The default Critic and seed data support these categories:

- retrieval miss
- citation error
- numeric conflict
- temporal conflict
- outdated source
- missing counterargument
- unverified projection

## Acceptance Criteria

- Evaluation can be run repeatedly from the command line.
- The output includes quality, citation, cost, latency, token, Critic catch rate, and aggregated bad-case fields.
- Critic issues are visible in the Streamlit dashboard and final report.
