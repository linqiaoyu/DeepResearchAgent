# R136 — MCP safety and Engine composition H2

## Verdict

PASS. H12 is complete and `mcp` is H2-ready. The capability remains default-off
and this mechanism verdict does not graduate MCP into the finance default.

## Safety closure

A duplicate namespaced capability is rejected before registration, leaving one
original capability and no partial second-server state. For an untrusted server,
annotations and metadata are ignored: cost remains `high`, side effects remain
possible, idempotence remains false, and a call without explicit paid permission
is rejected before consuming the remote request budget.

The Engine was composed with three independent failures: malformed JSON-RPC,
response timeout, and subprocess crash. All three appear as explicit failed MCP
registrations with distinct error classes. No failed remote capability remains,
while every baseline local capability remains available (retention 1.0).

R135 interoperability remains green: three successful stdio probes and zero
ResourceWarnings. No network, provider, paid, or remote Git write occurred.

## Falsification

The production untrusted default cost was temporarily changed from `high` to
`free`. The gate-wired probe exited 1 with
`mcp_safety_self_test=FAIL production probe is dirty`. Restoring the conservative
default returned all ten metrics to contract. Six output mutations also reject
collision acceptance, annotation trust, paid execution, silent failure, local
capability loss, and partially registered failed servers.
