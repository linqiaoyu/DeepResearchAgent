# R154 / F06 — Finance RAG disclosure timing

Status: PASS, with the two R149 diagnostic errors preserved exactly as required.

The frozen R149 cohort contains 30 explicit terminal records. Retrieval reached a live provider in 29 cases; 28 completed all three live layers, Q13 reached live retrieval and later hit the recorded planner timeout, and Q21 failed before any provider because of the recorded shared-ledger race. No missing case was filled from another run, and these denominators are not product acceptance metrics.

The finance RAG path now retains the source that established each disclosure date through corpus ingest, SQLite/Postgres storage, hybrid retrieval, Evidence retrieval references, and tool-call trajectories. A delivered candidate carries `index_version`, `published_at`, `published_at_source`, and `as_of_filter_reason`. The guard rejects both an erased provenance source and a fabricated claim that Q21 reached live retrieval.

The existing point-in-time guard still reports zero lookahead violations, with unknown disclosure dates withheld at every as-of. The shipped finance corpus has registered date provenance for 60/60 documents.

Three R154 capability deadlines were resolved as permanent opt-in: injection guarding, prior memory, and procedural memory. Each has H2 mechanism proof, but none has the powered finance experiment required by its registered graduation criterion; therefore none is promoted into the default SUT.

No provider call was made and paid cost was CNY 0. This round does not claim finance-quality benefit, a completed 30/30 product run, or RAG graduation.

The first full gate run failed because migration `008` had not yet been folded into the generated `docs/postgres_schema.sql`; this was a command/output synchronization defect, not suppressed. After running the repository generator, the full gate passed with 1221 tests, 7 registered skips, 57/57 guards wired, and no tracked-file mutation.
