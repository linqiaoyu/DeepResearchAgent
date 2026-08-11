# 122 result

`EpisodicMemory` and `ProceduralMemory` both declared
`lifecycle = "cross_run"`. Neither was.

## What was actually there

- The storage schema had five tables and none of them held memory.
- Nothing in production ever called `episodic_memory.write`. Not once. So
  `PRIOR_MEMORY_ENABLED` read an empty store no matter how many runs preceded
  it, and always would have.
- `procedural_memory.write` existed but wrote to an in-process dict built fresh
  per engine.
- `tests/unit/test_memory_flags_need_a_prior_run.py` recorded this as
  "unmeasurable on this instrument" in R109 and it stayed that way.

Two independent halves were missing, and fixing either alone changes nothing:
persistence with no writer stores nothing, and a writer with no persistence is
forgotten at process exit.

## What this round added

**A durable row, once, for both.** `memory_record(namespace, scope_key,
record_id, payload, created_at)` with a composite primary key, in the SQLite
schema and in `migrations/007_memory_record.sql`. The row is generic on purpose
-- storage does not import the memory layer, so a third memory kind needs no new
table and no second implementation to drift.

`scripts/check_storage_schema_parity.py` reports `tables=6 undeclared_diffs=0`:
both backends carry it identically, with no declared exception.

**Contract coverage.** `_assert_memory_contract` runs the same assertions
against every backend -- ordering, upsert-not-duplicate on a repeated key, and
that namespaces and scope keys are separate drawers. Per AGENTS.md §6 the
contract covers every protocol method, now 10 of 10.

**The missing writer.** The engine records an episodic snapshot at run
completion when `prior_memory_enabled` is on, next to the manifest it already
builds, degrading explicitly if the snapshot cannot be built.

**Injection, not inheritance.** Both memories take an optional store and fall
back to the old in-process behaviour without one, so every existing caller and
test is unchanged.

## The criterion

Set before the work: *the same question run twice, and the second run reads
what the first wrote* -- against `records_read` that was previously always 0.

```
test_a_second_run_reads_the_episodic_record_the_first_wrote      ok
test_a_second_run_reads_the_procedural_records_the_first_wrote   ok
test_dropping_the_store_leaves_the_second_run_blind              ok
```

The third is the counterexample: restoring the store-less construction makes the
second run read nothing again, so the assertions above cannot pass for a reason
other than the change.

## A coupling found on the way

`PROCEDURAL_MEMORY_ENABLED` on its own writes nothing, ever.
`_write_procedural_memory` is only called from `_reflector_node`, which
`_route_after_critic` reaches only when `REFLECTION_ENABLED` is true or the
research loop is active. Both default to false, so the flag was inert for a
second reason beyond the missing persistence.

The first engine test written for this round failed for exactly that reason and
was not worked around: `test_procedural_memory_writes_nothing_without_reflection`
pins the coupling, and says in its message to update this note if it ever stops
holding.

## Gate

```
storage_schema_parity=PASS tables=6 sqlite_columns=47 undeclared_diffs=0
Ran 1160 tests in 59.259s
OK (skipped=7)
[tracked_files_unchanged] gate created no tracked changes
gate_exit=0
```

The Postgres contract run is the registered skip served by the `postgres-storage`
CI job, which now exercises the new migration and both new methods.

## Not established

- **That reading memory improves an answer.** This round made the declared
  lifetime true. Whether a prior snapshot or an accumulated strategy history
  changes what the agent does is a separate question with its own experiment,
  and both flags stay off by default.
- **Semantic and working memory** were not touched; they are run-scoped and
  never claimed otherwise.
