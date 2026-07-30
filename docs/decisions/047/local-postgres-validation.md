# Local PostgreSQL validation

Round 047's PostgreSQL criteria are exercised against an explicitly configured
local PostgreSQL 15 profile, never the default CI profile. The default suite
continues to skip these tests when neither PostgreSQL DSN environment alias is
set.

The live guard proves both document-version deletion cascading to `chunk` and
checkpoint pause/resume using `langgraph.checkpoint.postgres`. The migration
idempotence guard was mutated by bypassing `if row:` in
`PostgresStore.apply_migrations`; the second migration attempt then failed with
the database's unique constraint on `schema_migrations.version`. The production
guard was restored before final verification.
