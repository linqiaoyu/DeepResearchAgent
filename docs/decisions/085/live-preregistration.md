# 085 live preregistration

Commit: `deab75a9fef2add34ddd74e01fa459162820dd8e`.

Hypothesis: full-subquestion period filtering, semantic error-page rejection,
source-URL footnote deduplication, source tiers, and verified filing dates will
improve reader-facing evidence without regressing structured numeric closure.

Two runs only: Chinese NIO and English PDD, both at `as_of=2026-07-01`, depth
1, live mode, SEC Company Facts, database `data/runtime/085-assets.db`, and
index `finance_v1-43f11085-heading_page_first_1024_256`.  The single-run cost
circuit breaker is CNY 15; the round total is CNY 20.  Stop on either breaker,
any mixed/fixture provider degradation, or a failed required-structured run.
Rollback is to retain the package and stop subsequent paid execution.

## Authorized retry

User authorized an additional paid retry after the initial three executions.
The retry commit is `7372acf50575191d671d08a1b1224faa678d8428`.  It fixes the
audit interpretation of a source-deduplicated footnote and gives the finance
domain's target report year delivery preference while retaining the preceding
year in the retrieval filter for YoY context.  Re-run only the NIO topic,
using the same command, providers, as-of date, database, index, and circuit
breakers as above.
