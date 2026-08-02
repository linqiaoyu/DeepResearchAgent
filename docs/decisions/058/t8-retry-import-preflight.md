# T8 real E2E retry: local import preflight blocked

Date: 2026-08-02

The user supplied fresh authorization for one T8 retry.  Before creating a
paid-run preregistration or invoking a provider, the round ran the required
zero-cost dependency preflight:

```sh
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -c \
  "import signal; signal.alarm(60); import akshare; import pandas; ..."
```

The process remained stuck in the local import after the alarm interval and
was interrupted.  After `scripts/doctor.py` repaired the editable-install
marker and confirmed the expected interpreter and package location, an
isolated `import pandas` preflight again remained stuck and was interrupted.

No LLM, search, structured-data, embedding, or rerank provider was invoked.
No paid-run preregistration was created, because the preregistration is the
immediate precondition for a provider call and the precondition to reach that
point is not met.  Observed cost is CNY 0.00.

Decision: T8 remains INCOMPLETE and blocked on repairing or replacing the
local Python/pandas import environment.  A future retry requires a fresh
zero-cost import preflight and, only after it passes, a newly committed paid
preregistration before its single authorized live attempt.
