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
