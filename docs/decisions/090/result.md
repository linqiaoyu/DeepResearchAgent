# 090 result

## What was wrong

`extractor` and `reporter` were the only two LLM roles configured with
`max_completion_tokens=1024`. That cap cannot hold either role's JSON schema, so
the provider stopped mid-object, the payload failed to parse, the client re-sent
it under the same cap, it failed again, and both agents degraded to their
deterministic fallbacks.

Measured over all 28 live packages of rounds 086-087
(`_collab/090/evidence/baseline_087_086.log` and the append-only LLM ledger):

| role | structured calls | parse errors | completion_tokens == cap | cap |
|---|---:|---:|---:|---:|
| extractor | 58 | 58 (100%) | 56 | 1024 |
| reporter | 56 | 56 (100%) | 56 | 1024 |
| planner | 28 | 0 | 0 | 8192 |
| judge | 3 | 0 | 0 | 8192 |

CNY 0.557778 of the rounds' CNY 0.891030 LLM spend (62.6%) bought responses that
were discarded. Every delivered report was assembled by deterministic code from
structured API records; `llm_authored_claims` was 0 in all 28 packages.

The cap was introduced by R073/R075 to fix a provider timeout. Those rounds also
bounded the *input* (12k prompt chars, 18 evidence entries), which did fix the
timeout and is retained unchanged. Only the completion cap was wrong.

## Why fifteen rounds of gates stayed green

1. The ledger stored `parse_error` as a bare boolean and never read
   `finish_reason`, so "we truncated the model" was indistinguishable from
   "the model wrote bad JSON".
2. `llm_stats.*.fallback` was recorded but no gate asserted on it.
3. `scripts/check_087_report_shape.py` required `reader_visible_lines <= 40`.
   Shorter was better, so the mechanical fallback's short, clean, fully-cited
   output scored as the best possible result.

Consequence: the eight capability A/B comparisons in
`docs/decisions/087/result.md` were all measured with both LLM agents dead and
with report length as the decision signal. Their `kept_off` conclusions for
RESEARCH_LOOP, SKILL_PACKS, TRAJECTORY_RECORD and PROGRESSIVE_DELIVERY carry no
information and must be re-measured in a separate round.

## Changes

- `extractor` and `reporter`: `max_completion_tokens` 1024 -> 4096,
  `timeout_seconds` -> 180. Sized from the observed ~75 tokens/s so a full
  response stays well inside the role timeout.
- `LLMClient` records `finish_reason` and classifies parse failures as
  `truncated` / `invalid_json` / `schema_violation`; a truncation raises
  instead of buying a second identical truncation; per-run structured-output
  health is aggregated into the audit bundle.
- `ReporterAgent`: numeric-fact deduplication now applies to claims that
  restate a number rather than to any claim citing already-cited evidence, and
  the finance reader report carries `## 详细分析` through when the reporter did
  not fall back. Both steps were deleting every analytical claim.
- `scripts/check_llm_agent_liveness.py` added to `scripts/gate.py`.

## Live validation: INCOMPLETE

The registered live runs did not execute. Three attempts were made on source
commit `c0c52b6`; **zero provider calls were made and CNY 0.000000 was spent**
(`llm ledger rows added = 0`, run manifest `provider_usage` all zero). The
authorized two-run budget is untouched.

| Attempt | Outcome | Evidence |
|---|---|---|
| 1 | Killed by a 10-minute foreground command timeout while still importing. Command-construction error, corrected by detaching. | `_collab/090/evidence/live_nio_zh_attempt1_import_stall.log` |
| 2 | Interrupted deliberately to obtain a Python traceback; confirmed the stall was `import litellm`, not a provider or network fault. | same file |
| 3 | Ran detached to completion and failed: `LLMRetryExhaustedError: LLM call failed for role=planner: LLM operation timed out after 60s; provider subprocess terminated` after 3 x 60s. | `_collab/090/evidence/live_nio_zh_attempt3_planner_timeout.log` |

Cause, by line: `LLMClient._call_with_hard_timeout` routes every production call
through `_call_litellm_in_subprocess`, and the child worker
(`src/deepresearch_agent/llm/client.py:40`) calls `import_module("litellm")` on
every single call. On this machine that import takes about 15 minutes -- the
parent process spent 15:15 of its 24 minutes inside it, at roughly 1-3 seconds
per file across litellm's 1812 modules, with total CPU under 5 seconds. Network
was verified healthy first: Qdrant, DeepSeek, DashScope and SEC all answered
within 0.3s. The per-call child therefore cannot finish importing inside any
role's timeout, so no live run can complete in this environment.

This is not a consequence of this round's changes: the planner role's 60s
timeout and 8192-token cap are untouched, and the failure occurs at the planner,
before any modified role runs. The same host completed live runs on 2026-08-03,
so the condition is environmental and recent.

Consequences:

- The offline acceptance criteria are met and gate-enforced. The claim "the LLM
  extractor and reporter no longer truncate" is proven only against a provider
  stub that truncates at `max_tokens`, never against a real provider. It must
  not be reported as a validated live result.
- Re-running the registered commands on a host without this condition is
  sufficient to close it; the preregistration and the two-run authorization
  stand unused.

New in-scope finding, not fixed this round: re-importing litellm per LLM call is
a real harness cost on any host, not only this one. Fixing it means a persistent
or pooled provider worker, which is a separate change with its own regression
surface and is named here rather than smuggled into this round.

## Contract change: report-shape acceptance

`reader_visible_lines <= 40` is replaced by `noise_lines == 0`, where
`noise_lines = boilerplate_lines + analysis_false_positives`. All other
criteria are unchanged: boilerplate, audit sections, metric coverage, derived
metrics and analysis false positives still gate. `reader_visible_lines` is
still measured and printed; it is no longer a pass/fail criterion, and it was
removed from the capability-A/B decision signal.

Reason: a cap on total reader lines makes an empty report the optimum, which is
the gate-side cause of this round's finding. Authorized by the user before
implementation.
