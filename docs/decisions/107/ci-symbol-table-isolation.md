# R107: symbol-table tests must use the current provider contract

## Context

CI run 31345662501 failed because the R111 symbol-resolution test still
stubbed the retired combined listing endpoint. R111 changed production code to
use two per-exchange endpoints and a disk cache. A local runtime cache hid the
mismatch, but CI's clean checkout correctly returned no table.

While making that test cache-isolated, its duplicate-name fixture also exposed
an upstream correctness flaw: the cache represented names with a one-to-one
dictionary, so the final code for a duplicated issuer name silently replaced
the first. A name lookup must be rejected as ambiguous, while an exact stock
code remains resolvable.

## Decision

- Update the provider test to stub the per-exchange endpoints and use a
  temporary cache path.
- Store code-to-name data separately from unique name-to-code data, retain
  ambiguous names explicitly, and reject ambiguous name queries.
- Version the disk cache. Pre-ambiguity cache files are invalidated and rebuilt
  instead of carrying the old lossy representation forward.

## Guards

`test_akshare_symbol_resolution_requires_one_exact_identity` now executes the
same endpoint and cache path shape as CI. `test_an_ambiguous_name_never_resolves_to_the_last_code_seen` fails if duplicate names are overwritten, and
`test_a_pre_ambiguity_cache_is_rebuilt` fails if an unversioned old cache is
accepted.
