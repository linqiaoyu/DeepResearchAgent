# B8 AKShare probe

akshare_version=1.18.64
akshare_symbol_resolve_seconds=48.027
akshare_financial_indicators_records=1

The 2026-07-28 direct, no-LLM probe first established the failure mode before
the repair: `symbol_resolve("宁德时代")` exhausted three independent 15-second
bounded attempts (`timeout after 15.000s`, 48.027 seconds total); the filtered
financial call returned zero records; and the unfiltered call exposed a
non-finite upstream value. The raw frame has an `指标` column and names annual
revenue `营业总收入`, while the request and fixture use `营业收入`.

The repaired filtered call, `financial_indicators("300750",
periods=["20241231"], metrics=["营业收入"])`, returned one record in 2.168
seconds: 362012554000.0 yuan. Its relative difference from the recorded fixture
value 362012600000.0 yuan is 1.270674004164495931909552319E-7. The repair is
limited to the observed `营业总收入` to `营业收入` provider alias and excludes
non-finite values before schema construction.

When the six-digit symbol is already supplied, `financial_indicators` no longer
calls `symbol_resolve`: the observed AKShare request count is 2 before the
change (financial frame plus full-market symbol table) and 1 after it. The
independent-worker retry repair was genuinely exercised by the standalone
symbol-resolution timeout: its three 15-second attempts completed independently
rather than queueing behind one hung worker. Raw, redacted probe output is
retained in the ignored 043 collaboration directory.
