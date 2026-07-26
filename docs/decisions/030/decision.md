# 030 disclosure routing

030 repaired three independent default-path breaks for explicit recognised A-share
financial-metric questions: the default rule now selects `disclosure_source`, the
LLM planner preserves topic-derived issuer identity in one financial branch, and
the default LLM engine passes its registered CNINFO source to `ResearcherAgent`.

The first real T2 attempt remains an unsuccessful acceptance result: it selected
disclosure but made zero disclosure calls, exhausted the shared Tavily fetch budget
at 20/20, and produced a missing-data report. The post-run inspection exposed the
third wiring break above. No later rerun was made to replace that result.

Evaluator diagnostics show that deterministic scoring cannot distinguish a correct
financial number from magnitude or decimal-place mutations when both retain the
same citation; it is therefore not a financial-numeric correctness gate.

The existing research loop measures aggregate evidence sufficiency only, not
whether each requested metric has cited coverage. A metric-level coverage contract
would require changes to planning, extraction, loop sufficiency, and reporting;
this was diagnosed but not implemented.
