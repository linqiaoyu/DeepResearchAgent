# 082 product-experience result

## Measured result

| package | cited evidence | RAG chunks | missing source dates | workflow CNY | RAG CNY | total CNY | realness |
|---|---:|---:|---:|---:|---:|---:|---|
| fixture-nio | 12 | 0 | 12 | 0.00000000 | 0.00000000 | 0.00000000 | fixture |
| live-nio-zh | 17 | 12 | 17 | 0.06271744 | 0.16661250 | 0.22932994 | mixed |
| live-pdd-en | 83 | 56 | 83 | 0.03774184 | 0.10063000 | 0.13837184 | mixed |

Both packages have `footnote_misrefs=0` and `magnitude_mismatches=0`; each has
`sampled_numbers=0`, because the current audit evidence export does not contain
the contract's structured `value + unit` fields. The two realness checks fail
because `structured_data=0` and `disclosure=0`, not because a fixture provider
was silently substituted. Therefore this round produced 2 live-LLM/live-RAG
packages but **0 qualifying three-layer-real packages**. Total paid cost is
**CNY 0.36770178**, below the CNY 20.00 circuit breaker.
