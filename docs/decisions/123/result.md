# 123 result

The agent could be used as an MCP tool and could not use one.

## What was there

`mcp/server.py` exposes `research.start`, `research.evidence`,
`research.audit_export` and `research.snapshot_compare`, and works.

`mcp/client.py` was complete too -- `MCPStdioClient.discover_and_register`
already put a discovered tool behind the same `CapabilityMetadata`, `ToolSpec`,
budget and `ReliableToolExecutor` as every local capability, recorded an
`AgentDecision`, and refused a name collision. It even had an end-to-end test
against this project's own server.

And nothing outside the `mcp` package imported it. No engine, no workflow, no
tool factory. So the capability registry held the same five hardcoded entries
whatever a server offered, and the client was a component with no consumer.

## What this round added

The production wiring, and nothing else the client did not already do:

- `MCP_CLIENT_ENABLED` (default false) and `DEEPRESEARCH_MCP_SERVER_COMMANDS`,
  a JSON list of `{name, command, environ?, timeout_s?, trusted?}`.
- The engine discovers each configured server while building its registry, and
  publishes `mcp_registration` -- enabled, configured, connected, failed,
  registered capabilities.
- A server is an outbound dependency, so unreachable is a degradation the run
  records and continues past. The same holds for malformed configuration.
- The flag is classified `content_affecting` in the manifest and has an
  observability locator, so a run can be asked whether it took effect.

## A bound the discovered tools were missing

`ToolSpec.total_timeout_s` defaults to `None`, which is the historical behaviour
for tools written in this repository and wrong for a remote one: it leaves the
retry envelope unbounded across attempts, and AGENTS.md §6 requires every
external tool to carry a bounded timeout and retry budget. A discovered tool now
gets an explicit ceiling of three times its per-attempt timeout, which a trusted
server may set for itself through `deepresearch/totalTimeoutSeconds`.

This was found by an assertion, not by reading: the test asserting every
registered remote spec is bounded failed with
`'>' not supported between instances of 'NoneType' and 'int'`.

## Acceptance

Against this project's own MCP server spawned over stdio -- a real server
speaking the real protocol, not a stub:

```
test_an_external_server_contributes_capabilities              ok
test_the_flag_off_registers_nothing                           ok
test_an_unreachable_server_degrades_instead_of_ending_the_run ok
test_invalid_configuration_is_recorded_not_raised             ok
```

The first asserts the remote capabilities appear in the registry *and* that
every one carries a positive `timeout_s`, a positive `total_timeout_s` and a
valid cost class. The second is the other direction: with the flag off, the same
configuration registers nothing. The third asserts the local capabilities
survive a failed server.

## A stale literal, fixed

`test_all_twenty_five_have_a_locator` asserted `len(provable) == 25` and broke on
the twenty-sixth flag. The count was incidental; the point is that no manifest
flag exists without a way to prove it ran. It now derives both directions from
`FLAG_CLASSIFICATIONS`, so a flag added without a locator fails there instead of
shifting a number.

## Gate

```
Ran 1164 tests in 59.164s
OK (skipped=7)
[tracked_files_unchanged] gate created no tracked changes
gate_exit=0
```

## Not established

- **That an external tool improves an answer.** The capability is reachable,
  bounded and observable; whether any particular server helps is a question for
  whoever configures one. The flag is off by default.
- **Skills** remain untouched, as this round's scope stated. `SKILL_PACKS_ENABLED`
  has never had a measured benefit, and where skill packs end and the domain
  pack begins is a product decision that belongs in AGENTS.md §1 before code.
