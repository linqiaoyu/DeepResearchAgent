# 031 first correct traceable financial answer

Round 031 produced the first accepted real end-to-end financial answer for the
requested Kweichow Moutai 2025 metrics. Accepted experiment A4f
`c86785db-245e-4c82-b6aa-fa141a86eab9` used the configured real DeepSeek LLM,
live AKShare structured data, and a live CNINFO disclosure fetch. It reported:

- revenue `168,838,102,514.79` yuan, 2024
  `170,899,152,276.34` yuan, down `1.21%`, annual report page 6;
- attributable net profit `82,320,067,101.68` yuan, 2024
  `86,228,146,421.62` yuan, down `4.53%`, annual report page 6 and corroborating
  `stock_financial_abstract.归母净利润` records;
- main-business gross margin for the liquor-industry total `91.23%`, down
  `0.78` percentage points, annual report page 10.

The run used one disclosure search plus two disclosure fetch requests, one
structured-provider call, and no Tavily web search/fetch calls. It cost CNY
`0.03550664`, used `30,948` tokens, and completed in `117.869512` seconds. Its
schema-v4 trajectory reproduced `report.md` byte-for-byte under strict offline
replay with all provider credentials removed.

The accepted result does not erase preceding experiments. A1 exhausted the web
budget before authority retrieval and answered zero of three metrics. A4e
answered all metrics correctly but failed strict replay because redaction
changed text offsets embedded in generated Evidence IDs. Evidence identity was
then based on stable run/source/metric/period fields while retaining offsets as
metadata; A4f proved the repair. A4b–A4d also exposed comparison-amount and
unsupported prior-rate assumptions, which were corrected without editing any
existing prompt.

The implementation isolates authority requests from web budgets, runs
structured and disclosure capabilities before optional web retrieval, parses
authoritative annual-report tables with period/scope/unit checks, tracks
requested metric coverage, mechanically audits every eligible reader-visible
financial line against its cited Evidence, downgrades unsupported numeric
assumptions, labels current-run and global ledger cost separately, and persists
typed completed/budget-exceeded/failed trajectory outcomes.

Generalization experiment A5 used Hengrui Pharmaceuticals, not a company
special case. Authority routing, annual-table extraction, metric coverage, and
strict replay worked, but the LLM key finding dropped one digit from the 2024
net-profit amount. The numeric evaluator caught it and forced task success to
zero. The result is therefore **partially degraded**, not universal; a future
generic repair should render required key findings from typed metric coverage
or suppress any mismatching key-finding line before release.

No prompt file, frozen Golden asset, or `tests/golden_output/` snapshot changed.
Trajectory recording remains default-off. Numeric auditing also remains
mechanical: direct `%` versus `percentage point` semantics are not yet distinct,
and an explicit-period-free derivation fallback remains. These limits do not
affect the accepted Moutai figures because their annual-report Evidence states
the values and percentage-point change directly.
