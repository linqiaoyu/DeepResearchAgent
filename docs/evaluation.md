# Evaluation Harness

The harness treats evaluation as a first-class subsystem, not a screenshot.

See [`method_limits.md`](method_limits.md) for the boundary between detecting
behavior changes and interpreting quality for Evidence-changing controls.

Cross-generation comparisons must first pass `scripts/verify_manifest.py`.
Model, prompt, evaluation-clock, dependency, domain, mode, and
content-affecting flag differences make runs incomparable. Operational flag
differences are reported as informational without blocking comparison.
Treating every flag as content-changing is too strict: it prevents legitimate
quality comparisons just as a permissive check can create false improvements.
The classification is grounded in the prior product-level flag-impact replay,
not flag names or implementation claims; unknown flags fail closed as
content-affecting until measured.

## Metrics

The current runtime metric contract is summarized below. Historical Golden-set
comparison tables retain their original columns because they record released
results rather than define a live scoring contract.

| 指标 | 算子 | 输入 | 值域 | 是否 gated |
| --- | --- | --- | --- | --- |
| `task_success_rate` | final-report/evidence/required-output/numeric-audit conjunction | `ResearchState`、计划指标覆盖、机械数值审计 | `{0, 1}` | 单任务状态；非 baseline diff gate |
| `citation_accuracy` | deterministic support audit or semantic judge | report claims、footnotes、Evidence | `[0, 1]` 或 `null` | 是 |
| `citation_resolution_rate` | resolved citations / citation markers | report footnotes、Evidence | `[0, 1]` | 是 |
| `bbox_resolution_rate` | valid layout anchors / paged numeric Evidence | `Source.bbox_index`、numeric Evidence | `[0, 1]` 或 `null` | 否（display-only） |
| `critic_catch_rate` | deterministic visible-issue proxy | Critic issues | `[0, 1]` | 是 |
| `lexical_overlap` | deterministic topic-token overlap | topic、final report | `[0, 1]` | 否 |
| `citation_density` | cited bullet claims / all bullet claims | rendered claims、citations | `[0, 1]` | 是 |
| `semantic_relevance` | enabled semantic judge | topic、final report、Evidence | `[0, 1]` 或 `null` | 否 |
| `semantic_faithfulness` | enabled semantic judge | report、Evidence | `[0, 1]` 或 `null` | 否 |
| `cost_cny` / `cost_usd` | LLM ledger aggregation / display conversion | LLM ledger | `>= 0` 或 `null` | 否 |
| `latency_seconds` / `token_used` | run aggregation | run telemetry / LLM ledger | `>= 0` 或 `null` | 否 |

### Retrieval metric contract (047)

This contract applies to the immutable `retrieval_v1` dataset. It does not
reinterpret any Golden Set v1 result. Its source corpus and source-span labels
are frozen separately from the historic Golden Set v1 assets.

| Metric | Operator | Input | Range | Gated |
| --- | --- | --- | --- | --- |
| `Recall@20` | relevant chunks returned in the first 20 / all resolved relevant chunks | ranked `chunk_id`s and source-span labels resolved against one `index_version` | `[0, 1]` | Yes, test split: fail below `0.85` |
| `nDCG@10` | DCG with gain `2^relevance - 1` and discount `log2(rank + 1)`, normalized by ideal DCG | ranked `chunk_id`s and relevance `{1, 2}` after source-span resolution | `[0, 1]` | Yes, test split: fail below `0.75` |
| `nDCG@10` lift | `nDCG@10(hybrid+rerank) - nDCG@10(BM25 + entity/period filtering)` | the same frozen test split, corpus version, `as_of`, and index version for both systems | `[-1, 1]` | Yes, test split: fail below `+0.10` |

Labels are source spans, not `chunk_id`s: a chunk is relevant when its
`(document_version_id, char_start, char_end)` overlaps a labelled span. Ties
are resolved deterministically by `chunk_id`. Threshold selection may read
only the frozen dev split (24 questions); the test split (36 questions) is
run once as the pre-registered gate. The current repository has no
`retrieval_v1` outcome embedded in this document; measured values are saved as
versioned result artifacts. Questions whose expected behavior is refusal have
no relevant spans and are reported separately from answerable-query means, so
the empty-relevance convention cannot inflate retrieval quality.

- `task_success_rate`: requires a final report, at least one evidence record,
  zero detected financial numeric-citation mismatches, and a terminal outcome
  for every typed financial metric request. A metric must be cited, explicitly
  searched-unavailable, or have an observed comparison that covers its missing
  period; a missing required metric forces this value to `0`. In every
  execution mode, any detected mismatch also forces this metric to `0`.
  In LLM mode a value of `1` does not imply that unresolved citations,
  non-financial semantic support, Critic issues, or requested-metric completeness
  all passed.
- `citation_accuracy`: in deterministic mode, citation markers in bullet claims
  map to Evidence rows and use deterministic text/numeric support checks. In LLM
  mode with `SEMANTIC_JUDGE_ENABLED=true`, the typed semantic judge scores claim
  support against the exact `report_footnote_evidence` mapping and the result is
  capped by the mechanical citation-resolution rate. When the judge is disabled,
  unavailable, or fails, this field is `null` with an explicit reason; the
  mechanical numeric audit still applies to task success.
- `citation_resolution_rate`: citation markers that resolve to real Evidence rows, computed in both deterministic and LLM modes
- `bbox_resolution_rate`: among numeric Evidence rows carrying a source page,
  the share with a valid PDF layout anchor `(page, x0, top, x1, bottom)`.
  It is `null` with reason `no_paged_numeric_evidence` when a run has no such
  rows; it is currently display-only and does not alter task success or
  cross-run quality gates.
- `citation_repair_retry_rate`: Golden Set mechanical metric equal to the share of runs where Reporter performed one structured evidence-id repair retry before rendering
- `uncited_claim_rate`: Golden Set mechanical metric equal to uncited rendered ReportClaims divided by all rendered ReportClaims
- `critic_catch_rate`: MVP heuristic/proxy for whether the Critic exposed quality issues. Current deterministic logic scores visible issue coverage, using `min(1.0, len(issues) / 3)` when issues are present and `1.0` when no issues are found. It is not true seeded issue recall or human-labeled Critic recall.
- `answer_completeness`: optional semantic-judge assessment of whether the
  report covers the material parts of the topic, plan, and available Evidence.
  It is `null` outside an enabled, successful semantic-judge call.
- `lexical_overlap`: deterministic share of topic tokens appearing in the final
  report. It measures token overlap, not answer relevance.
- `answer_shape`: optional semantic-judge assessment of whether the result is a
  usable answer with synthesis, findings, qualifications, and appropriate risks.
  It is `null` outside an enabled, successful semantic-judge call.
- `citation_density`: deterministic share of rendered bullet claims containing a
  citation. It is not semantic faithfulness.
- `semantic_relevance` and `semantic_faithfulness`: optional judge outputs;
  both are `null` outside an enabled, successful semantic-judge call.
- `cost_usd`, `cost_cny`, `latency_seconds`, `token_used`, `price_source`: operational metrics for Pareto analysis. LLM mode accounts natively in CNY from the LiteLLM ledger.

`comparison_observed` in metric-coverage output is display-only provenance: it
reports whether matched evidence text contains a comparison phrase such as
“同比”. It does not participate in coverage status, metric gates, or task
success, which are determined only by requested periods and cited Evidence.

The mechanical financial numeric-citation audit runs in every execution mode
and recognizes revenue, net profit, gross margin, and operating-cost amounts or
rates across eligible reader-visible content lines, including the non-bulleted
summary. Headings and footnote-definition lines are skipped. A financial value
without an explicit resolvable citation therefore fails the audit instead of
escaping bullet-only scoring. Mismatches are counted by line, so several wrong
values on one line contribute one mismatch line. Citation-resolution and
lexical-support metrics remain bullet-line metrics.

Runtime semantic evaluation is an optional, default-off LLM-mode step routed
through the same `LLMClient` ledger and budget boundary as generation. Its
typed contract covers completeness, relevance, answer shape, semantic citation
support, and whole-report faithfulness. The judge receives the topic, typed
plan, report, exact footnote-to-Evidence mapping, and a bounded representation
of every Evidence row. It is explicitly forbidden to judge exact values,
arithmetic, units, decimal placement, magnitude, period alignment, or direction.
Those decisions remain exclusively mechanical, and semantic scores cannot
change `task_success_rate` or erase `numeric_citation_mismatch`. Enabling the
judge requires `DASHSCOPE_API_KEY`; deterministic and default LLM paths require
no judge key or judge call. Budget and cost-overrun exceptions retain the
run-level terminal behavior instead of being downgraded to missing metrics.

The audit normalizes `元`/`万元`/`亿元`, allows rounding within half of the
displayed numeric resolution, and preserves increase/decrease direction from
words such as `增长` and `下降`. Years, footnote numbers, and page locators are
not treated as financial values. Resolution uses only
`report_footnote_evidence`; positional Evidence inference remains prohibited.
Given two distinct source-backed values, it may mechanically derive an amount
YoY rate or a rate percentage-point change, preferring explicit period order
when two periods are available. It never reverse-derives a prior rate from a
current rate plus a claimed change. A compatibility fallback can still derive
from encounter order when explicit periods are absent, and direct rate parsing
does not yet distinguish `%` from `百分点`; both are documented gaps for future
hardening.

When enough ordered header years are parseable, financial-statement column
headers bind each value to its year. Conflicting LLM-normalized period/value
pairs are rejected when the source excerpt exposes a parseable candidate for
the normalized metric/kind and the claimed period; a source without such a
candidate cannot receive the same period check. `营业总收入` and `营业收入` are
separate metrics rather than aliases.
An unqualified gross-margin request routed as `主营业务毛利率` additionally
requires a main-business total dimension such as `酒类` or `小计`; product,
region, and channel rows cannot close that slot or support its numeric claim.
For text Evidence, source truth comes from verbatim `extract_text`; an
LLM-produced `claim` is never treated as independent support, and normalized
numeric fields are used only when their metric and value occur in that
excerpt. Structured records remain authoritative at their typed interface
boundary. The audit is deliberately mechanical rather than a semantic LLM
judge.

For metric-scoped financial reports, Reporter applies targeted pre-render
numeric guards to the summary, risks, and unverified assumptions. A summary
containing recognized financial numbers is replaced with a fixed nonnumeric
summary because it has no per-value Evidence binding, risks containing unbound
financial numbers are downgraded to qualitative warnings, and each unverified
assumption is audited against the union of its own `evidence_ids`. Unsupported
numeric assumptions are replaced with a qualitative warning that retains any
valid citations, and their provenance records `numeric_downgraded=true`;
nonnumeric assumptions are not numerically downgraded. Key findings and
detailed-analysis claims remain subject to the post-render Evaluator audit.

Unresolved bullet citations are counted as `citation_error` in every mode.
Resolved-but-lexically-unsupported citations add that category only in
deterministic mode; optional LLM semantic support is reported as a score rather
than rewritten into the mechanical bad-case count. A
recognized financial value that is not supported by its explicitly cited
Evidence union additionally records
`numeric_citation_mismatch` and forces task success to zero in every mode. It
also lowers deterministic citation accuracy. LLM citation accuracy is semantic
only when the optional runtime judge succeeds and otherwise remains explicitly
`null`. Golden Set LLM rounds separately run their frozen judge-backed
`citation_support_rate`; that benchmark judge contract is not the runtime
Evaluator contract.

Round 031 regression tests cover magnitude, decimal-place, and
comparison-direction mutations. Each mutation produces
`numeric_citation_mismatch` and forces `task_success_rate=0`; the unchanged
cited report remains accepted. In LLM mode, the same mechanical failure applies
regardless of whether the optional semantic judge returns a score or remains
disabled.

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

Golden Set v1.1 uses the retrieval-corpus evaluation clock
`retrieval_corpus_as_of=2026-07-09`, the last frozen-corpus recording date. The
separate gold-appendix provenance clock is `gold_appendix_captured=2026-07-12`;
the appendix is isolated from retrieval and does not change evaluation time. The frozen corpus contains
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
  --as-of 2026-07-09 \
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
normalizes finance metrics with `skills/finance-metric-normalization/resources/finance_metric_normalization.json`, parses
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

### 指标覆盖状态契约

指标覆盖状态区分 `cited`（所有请求期间均有可引用证据）、`partially_cited`（已有
可引用证据但仍缺少请求期间）、`searched_unavailable` 和 `not_attempted`。`partially_cited`
必须同时输出已观察期间与缺失期间；它不会把单期证据或“同比”文字当成缺期数值的证明。

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
| avg citation support rate | 0.8883 | 0.7227 | 0.7376 |
| avg citation resolution rate | 0.6000 | 1.0000 | 0.9333 |
| avg citation repair retry rate | 0.0000 | 0.0000 | 0.5333 |
| avg uncited claim rate | 0.0000 | 0.0000 | 0.0779 |

The official side-by-side v1.0/v1.1 dimension table and all 30 per-question
rows are generated in
`data/golden_set/v1/results/v11_three_point_comparison.md`. Composite deltas
versus historical v1.0 are `+0.0338`, `+0.0300`, and `+0.0179` for G1, G2, and
G3. These are gold-version movements, not new product-generation results, and
remain subject to the documented cross-generation and judge test-retest bands.

The two false-premise cases scored `false_premise_failed=false` in all three
saved generations under v1.1:

| Case | G1 weighted / citation rate | G2 weighted / citation rate | G3 weighted / citation rate | Recorded verdict |
| --- | ---: | ---: | ---: | --- |
| Q08 | 0.7525 / 1.000 | 0.7575 / 0.833 | 0.8425 / 0.667 | `false_premise_failed=false` |
| Q16 | 0.8400 / 0.917 | 0.8875 / 1.000 | 0.8800 / 0.250 | `false_premise_failed=false` |

> **R115 correction.** This paragraph previously read "remain correctly refuted"
> and labelled the Behavior column `refuted`. That was an inference from a metric
> that could not report anything else: the pre-R115 `false_premise_failed`
> substring-matched `gold.must_not_assert`, whose frozen entries are prose
> behaviour descriptions, so no report could satisfy it. The verdicts in this
> table are what the metric printed; they are not evidence that either premise
> was refuted, and they were not re-scored, because these are archived
> generations whose reports were produced under a different fidelity. The R113
> live generation *was* re-scored under the R115 criterion and both cases fail
> — see `docs/decisions/115/`.

The three v1.1 judge rounds cost CNY `1.65913960`, `1.67774040`, and
`1.65709656`, respectively, for a combined CNY `4.99397656`. The shared task
ledger contains 271 judge rows and 91 citation_support rows; two additional
rows beyond the nominal 360 calls are recorded structured-repair attempts.

For the v1.1 release, G3 `citation_support_rate` is upgraded from the archived
single-sample `0.7640` to `0.7376`: three verifier calls per question, with a
per-claim majority vote and ordinal-median tie break for a three-way split. The
change is `-0.0264`; historical single-sample values remain labelled as such.

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

### Golden v1.1 Dual Clocks

Recording `as_of` is source provenance and may have multiple values inside a
frozen corpus. The release evaluation clock is instead
`retrieval_corpus_as_of=2026-07-09`, the final recording date of the unchanged
retrieval corpus; it controls freshness-sensitive replay rules. The corpus
retains source recording dates `2026-07-08` and `2026-07-09`.

`gold_appendix_captured=2026-07-12` is a separate provenance timestamp for the
isolated gold appendix. It is not a retrieval input, does not change the corpus
fingerprint, and does not enter judge or citation_support prompts or scoring.
The v1.1 freeze note records the correction from the previously conflated
`evaluation_as_of` field; saved result JSON timestamps remain historically
unchanged.

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

`data/eval_baseline.json` preserves the original deterministic MVP baseline for a 5-case
local sweep. The current CI baseline is `data/eval_baseline_v2.json`; compare a new run
against that current contract with:

```bash
PYTHONPATH=src .venv/bin/python scripts/run_eval.py --limit 5 --compare-baseline --baseline-path data/eval_baseline_v2.json
```

Use a custom baseline path when validating an experiment:

```bash
PYTHONPATH=src .venv/bin/python scripts/run_eval.py --limit 5 --compare-baseline --baseline-path artifacts/evaluation/latest_metrics.json
```

The current comparison gates quality regressions for `avg_citation_accuracy`,
`avg_citation_resolution_rate`, `avg_citation_density`, `avg_critic_catch_rate`, and
total bad-case count. `avg_task_success_rate` is emitted for task-level diagnosis but
is not in `QUALITY_METRICS`; `avg_faithfulness` is a historical name, not a current
runtime metric (the optional runtime field is `avg_semantic_faithfulness`).
`avg_cost_usd`, `avg_latency_seconds`, and `avg_token_used` are reported as
operational diffs; latency changes are informational so local machine variance
does not fail the smoke check. Deterministic fixture runs deliberately report
cost and token metrics as unavailable: only an `LLMClient` ledger can populate
those fields.

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
| `avg_cost_usd` | unavailable (fixture run) |
| `avg_token_used` | unavailable (fixture run) |
| `bad_case_categories.numeric_conflict` | `6` |

The baseline comparison status is `pass`. Latency is reported as an
informational operational diff because it varies by local machine.

### 039 baseline refresh

`data/eval_baseline_v2.json` was refreshed in round 039 after enabling the
deterministic per-branch budget by default. This changes the fixture evidence
selection path and therefore its characterization metrics. The refresh also
records `avg_cost_usd` and `avg_token_used` as `null`: deterministic runs do
not use an LLM ledger and must not publish synthetic operational figures.

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

Evaluator additionally emits `numeric_citation_mismatch`. It is a mechanical
report-to-source failure category, not a Critic issue type.

## Acceptance Criteria

- Evaluation can be run repeatedly from the command line.
- The output includes quality, citation, cost, latency, token, Critic catch rate, and aggregated bad-case fields.
- Critic issues are visible in the Streamlit dashboard and final report.
### Reporter footnote contract

Reporter persists the emitted footnote-to-evidence mapping with the report.
Evaluator and audit export consume that mapping directly and never reconstruct it
from the current Evidence order. A historical saved state without the mapping is
marked degraded, so citation resolution cannot fail silently. Historical public
release results are unchanged: their reports and saved Evidence were produced and
evaluated under the same canonical order; this repair makes that formerly implicit
condition explicit without changing any scoring formula.

## R095 contract change: `critic_catch_rate` counts problems, not sentences

Previously `critic_catch_rate = min(1.0, len(issues) / 3)`. That counted issue
objects, so a critic that repeated one warning once per affected claim scored
higher than one that said it once. R094 delivered the same stale-source warning
five times to the reader for that reason, and deduplicating it registered as a
0.066 quality drop against the baseline.

It is now `min(1.0, sum(max(1, len(issue.affected_claims)) for issue in issues) / 3)`.
An issue records every claim it affects, so merging duplicate messages leaves
the measurement unchanged while removing the repetition from the report. The
denominator and the 1.0 cap are unchanged, and `data/eval_baseline_v2.json` is
unchanged: the deterministic eval scores the same 0.933 before and after.

## R115 contract change: `false_premise_failed` reads the frozen numbers

`false_premise_failed` was:

```python
def false_premise_failed(report, must_not_assert):
    text = report.replace(" ", "")
    if "假前提" in text or "前提不成立" in text or "并未" in text or "未被" in text:
        return False
    return any(item.replace(" ", "") in text for item in must_not_assert)
```

`gold.must_not_assert` holds prose behaviour descriptions. Q16's only entry is
`承认"被反超"并展开分析`; Q08's is `任何顺应假前提编造的"下滑原因"`. The final
branch therefore asked whether the report contains a sentence describing what the
report must not do, which no report contains, so the metric could not return
`True` on frozen data. The short circuit made it unreachable twice over: `并未`
is ordinary Chinese, and any report using it returned `False` before the
comparison ran.

The consequence was published. R113 reported `false_premise_failed=0/30` for a
Q16 report whose summary opens 「2024年，宁德时代全球动力电池装机量市场份额被比亚迪
反超，主要源于…」 — the false premise asserted as fact in the first sentence — and
which states none of the four SNE Research figures the gold requires.

It is now the negation of a behavioural verdict:

> A report refutes a premise when it states what is actually true. The verdict is
> satisfied when the report body states **every** `numeric_tokens` entry of one
> `must_include` fact whose `audit_contract` carries them, compared as values
> within that fact's `tol`, normalised across the 百/千/万/亿 and percent scales,
> with the `## 参考来源` section excluded.

Nothing in `data/golden_set/` changed. The criterion reads fields the frozen set
already published — Q08 `1741.44`/`15.66`, Q16 `339.3`/`37.9`/`153.7`/`17.2` —
and adds no truth of its own. Excluding the reference list matters: an
`akshare://营业收入/600519/20241231/…` footnote carries an issuer, a metric and a
period that were never said to the reader.

Scope of the change:

- `false_premise_failed(report, gold)` replaces `false_premise_failed(report, must_not_assert)`.
- Per-question results gain a `behavioral` map of criterion → verdict.
- The four weighted judge dimensions and their weights are unchanged, and
  `data/eval_baseline_v2.json` is unchanged; `false_premise_failed` has never
  been a weighted term. It feeds the `假前提未识破` bad-case category, which can
  now be non-empty.
- Historical rounds are **not** re-scored. Their recorded `false_premise_failed`
  values remain as printed, and are labelled above as metric output rather than
  as refutation.

`gold.behavioral` has a second key, `counterview`, required by Q11, Q17, Q18,
Q19, Q20, Q22 and Q28 and read by nothing. It is registered as deferred in
`data/behavioral_criteria.json` with its reason and owning round;
`scripts/check_behavioral_criteria.py` fails closed on any behavioural key that
is neither implemented with separating fixtures nor registered as deferred, and
the deferred count is a ratchet.
# R125 product acceptance contract

Product completion is now a single-cohort claim, not the absence of a known
regression. `data/product_acceptance.json` requires one preregistered 30-case run
with live LLM, retrieval, and structured-data providers to satisfy all of these
reader-visible thresholds at once: `evidence_reachable_rate >= 0.60`,
`orphaned_sub_questions == 0`, and `false_premise_failed == 0`. The first target
starts from R116's measured 0.27 baseline; it is a convergence target, not a
claim that the current product already passes.

`scripts/check_product_acceptance.py` refuses best-of or cross-round splicing.
At the target round it reads the published `run_golden_round.py` JSON itself,
requires exactly 30 completed cases and three-layer live fidelity, and recomputes
the metrics from case results. A handwritten proof summary is not accepted.

# R126 phased Harness and product acceptance

The approved delivery order is now machine-readable rather than implicit:
Harness H2 first, then finance-product H3. `data/harness_acceptance.json` fixes
twelve Agent-technology families and an R150 deadline. A family may be
`absent`, `wired`, or `h2_ready`; only a published proof whose numeric metrics
meet the frozen per-family contract may claim `h2_ready`. Existing production
code is initially recorded as `wired`, not prematurely promoted.

The finance product deadline moves once from R140 to R160 to make room for the
separately falsifiable H2 work. The product cohort, three-layer live fidelity,
reader-visible metrics, thresholds, and prohibition on best-of or cross-round
splicing are unchanged. The nine default-off capability decision rounds are
rescheduled between R151 and R158 so their finance defaults are decided after
the H2 mechanism proof and before the R160 product proof; their graduation
criteria are unchanged.

# R149 evidence-funnel diagnostics

The golden runner persists a per-case `evidence_funnel` with five direct
delivery counts: unique `retrieved_sources`, `extracted_evidence`,
`packed_evidence`, representative `cited_evidence`, and
`reader_visible_evidence`. These are diagnostic counts with explicitly
different units at the retrieval and evidence stages; they are not a new
product threshold and do not change golden scoring. Terminal errors still
carry all five fields with the counts available before failure, or zeros when
no state was produced.

# R149 stage-two execution amendment

R149 is a loss-diagnostic census, not a product-acceptance candidate. All 30
fixed questions must reach a terminal artifact, but diagnostic metrics use only
successful cases and must print that denominator. A terminal provider or
Harness error remains in the cohort; it is not rerun, silently excluded or
filled from another round. Consequently, a complete diagnostic may still carry
`product_acceptance_status=incomplete`, and its three diagnostic values are not
formal product metrics.

There is no full-cohort F01 recovery run. F11 is instead a preregistered fixed
6-10 case, three-layer-live reliability canary and cannot prove product quality
or contribute cases or scores to the final proof. F13 is conditional on a
failed full product acceptance rather than a scheduled repeat. F14 is the sole
planned full 30-case, three-layer-live product candidate; only a failure may
trigger a defect-class repair and a new independent full candidate. F15 makes
no paid provider calls. The R160 thresholds, frozen cohort, and prohibitions on
saved states, best-of selection and cross-run splicing are unchanged.

The R149 diagnostic reached 30 terminal artifacts but only 28 successful cases;
Q13 was a bounded planner retry exhaustion and Q21 was a cross-process ledger
index collision. Its diagnostic values therefore use denominator 28 and are not
formal product metrics. The subsequent four-process ledger probe and three-call
live planner probe validate only the repaired Harness mechanisms. They rerun no
golden question and cannot contribute to F11 or F14 quality evidence.

# R150 pre-writing Evidence selection

Before Reporter writes, every planned sub-question now receives exactly one
typed Evidence-selection decision. An evidenced sub-question selects a bounded
set of IDs owned by that sub-question; an unevidenced one explicitly degrades.
Context omission is distinguished from absence of canonical Evidence and is
routed to the mechanical evidence floor. The selection contract is diagnostic
and does not change a golden truth or product threshold. Reader-visible
coverage of the selected IDs is measured separately in F03.
