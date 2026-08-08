# 091 result

## What was wrong

Every production LLM call spawned a fresh process that imported the provider
SDK from scratch, and the parent process imported it a second time for a value
production never used.

- `LLMClient._call_with_hard_timeout` routed all production calls to
  `_call_litellm_in_subprocess`, whose worker called `import_module("litellm")`
  on every call.
- `LLMClient.__init__` also imported litellm eagerly, only to bind
  `self._completion = self._litellm.completion` -- which the production path
  never calls, because production goes through the subprocess.

litellm is 1812 modules. On a normal host this is seconds per call; on the R090
run host it was about 15 minutes, which is why no live run could complete:

```
LLMRetryExhaustedError: LLM call failed for role=planner:
LLM operation timed out after 60s; provider subprocess terminated
```

The import is local work, not a provider transport, but it was being charged to
the role's call timeout.

## Change

- `_litellm_worker_loop` + `_ProviderWorker` + `_ProviderWorkerPool`: one
  spawned worker per calling thread imports the SDK once and then serves calls.
  Workers are per-thread so branch fan-out keeps its parallelism.
- Worker startup gets its own budget (`DEEPRESEARCH_PROVIDER_WORKER_STARTUP_TIMEOUT`,
  default 900s) and no longer consumes the call timeout.
- The killability contract is unchanged: an overdue call still terminates its
  worker, and that worker is dropped so a late response can never be handed to
  the next request. A provider *error* keeps the worker, because a refusal is
  not a hung transport.
- `LLMClient.__init__` no longer imports the SDK in the parent at all.
- `_call_litellm_in_subprocess` is unchanged: `scripts/check_081_accounting.py`
  and `tests/unit/test_llm_integration.py` use it as the guarded one-shot
  primitive.

## Measured

`scripts/check_provider_worker.py --self-test`, now in `scripts/gate.py`:

```
parent_process_imports_sdk=false
worker_spawns=1 provider_calls=5 litellm_imports=1
timeout_kills_worker=true next_call_gets_fresh_worker=true
slow_startup_does_not_consume_call_timeout=true
provider_worker_failures=0
```

Constructing a production `LLMClient` went from a full SDK import to
`production_client_construction_seconds=0.0` with
`litellm_imported_in_parent=False`.

Each property has a saved counter-example under `_collab/091/evidence/`:

| Mutation | Result |
|---|---|
| never reuse a worker (pre-R091 behaviour) | `worker_spawns=5 litellm_imports=5`, exit 1 |
| do not terminate an overdue worker | `timeout_kills_worker=false`, exit 1 |
| charge worker startup to the call timeout | `slow_startup_does_not_consume_call_timeout=false`, exit 1 |
| restore the parent-side import | `parent_process_imports_sdk=true`, exit 1 |

The import count is measured by counting the distinct worker pids that served
the calls, not reported by the stub, so it cannot pass vacuously.

## Live validation

Two paid attempts on this blocker, then a self-imposed stop before a third.
Round total **CNY 0.265327**, inside the CNY 1.5 breaker; each run inside the
CNY 0.5 per-run breaker.

### Attempt 1 (`_collab/091/evidence/liveness_attempt1.log`)

First run ever to complete end to end on this host. The provider worker worked
as designed:

```
provider_worker_started startup_seconds=1.952 import_seconds=1.486
planner  finish_reason=stop  completion_tokens=1321  truncated=False
```

R091's own target is therefore validated live, not only offline: one worker,
sub-two-second startup, and the parent reaching the planner node 5ms after
`run_started` instead of 15 minutes.

It also produced the first real evidence for R090's other change:
`truncated_calls=2` for two truncated roles, where R086/R087 recorded 4 -- the
wasted repair call under an unchanged cap is gone.

Both the extractor and the reporter still truncated, at the new 4096 cap, with
`finish_reason=length`. R090's cap came from an estimate; this is the
measurement that estimate was missing.

### Attempt 2 (`_collab/091/evidence/liveness_attempt2.log`)

With both roles at the 8192 default and the prompts bounded to the renderer's
own limits:

```
extractor_fallback=1 reporter_fallback=0 structured_parse_errors=1
truncated_calls=1 llm_authored_claims=4 reader_analysis_lines=0
orphan_footnotes=6
reporter  finish_reason=stop  completion_tokens=6946  truncated=False
extractor finish_reason=length completion_tokens=8192 truncated=True
claim provenance: first_pass=4, mechanical_grounded_fact=2
```

**The reporter LLM path ran for the first time since R075.** Every one of the
30 packages in R086-R091 attempt 1 recorded `reporter_fallback=1` and
`llm_authored_claims=0`; this package records `0` and `4`. The delivered report
gained a substantive `## 风险与限制` section -- missing 2023 comparatives,
missing segment breakdown, an unlabelled unit in the cash-flow extract, and
EDGAR-versus-filing rounding differences -- and two cited unverified
assumptions. None of that existed in any prior delivery.

The reporter needed 6946 completion tokens, which is why 1024 and 4096 both
failed and why the cap is now measured rather than estimated.

## Still open, by line

- **INCOMPLETE (high)**: the extractor truncates at 8192 too. Raising the cap
  is chasing the model; the output needs a structural bound.
  `src/deepresearch_agent/schemas.py` `ExtractedClaims.claims` and
  `ExtractedClaim.extract_text` are both unbounded, so the JSON Schema sent to
  the model states no limit and validation enforces none. Named, not fixed:
  after two paid attempts on this blocker the round stops spending.
- **INCOMPLETE (high)**: `reader_analysis_lines=0` despite four authored
  claims. `src/deepresearch_agent/agents/reporter.py` `_render_llm_report`
  keeps a `detailed_analysis` claim only if it shares evidence or a fact key
  with a key finding. The key findings here are the mechanical structured
  facts, while the model's analysis cites 20-F chunks, so every analysis claim
  was routed to `补充事实` and dropped by the compaction step.
- **INCOMPLETE (medium)**: `orphan_footnotes=6`, unchanged in kind from R090.
