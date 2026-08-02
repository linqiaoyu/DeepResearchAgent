# 056 Engineering hygiene batch

## Decision

- Finance issuer aliases remain optional retrieval metadata: importing the
  finance pack performs no asset read, and a missing asset raises a path-bearing
  `ValueError` only when retrieval filtering requires it.
- Qdrant query validates a prebuilt collection read-only. Missing collections,
  dimension conflicts, and index-version conflicts raise `ToolExecutionError`
  so the RAG executor records a bounded degradation rather than mutating a
  production index.
- Trajectory strategy configuration derives from `asdict(Settings)`: every
  boolean setting is retained automatically and the explicit non-boolean
  whitelist covers replay-relevant budgets and retrieval controls.
- Package facades use the same export-table lazy-resolution pattern. Public
  symbols are guarded by iterating each `__all__`.
- Live package RAG budget is `Settings.rag_budget_cny` (`DEEPRESEARCH_RAG_BUDGET_CNY`,
  default 12.0), and scripts use `engine.close()` rather than the private
  checkpoint connection.
- Gate and test-spawned subprocesses use `stdin=subprocess.DEVNULL`. The
  complete gate passes when launched from an open `yes` pipe.

## Verification

- Dedicated engineering/Qdrant tests: 14 passed.
- Qdrant mutation restoring `ensure_collection()` made the read-only test fail
  (`put.call_count` became 4); strategy and gate-stdin mutations also failed.
- `yes | scripts/gate.py` and the ordinary complete gate both passed.
- Both direct combined hosts pass: continuous open pipe completed 719 tests in
  38.584 seconds and `/dev/null` completed them in 37.961 seconds. The earlier
  interrupted observations were insufficiently bounded waits, not a retained
  stdin dependency.
