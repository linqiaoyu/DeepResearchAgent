# Rerank evaluation-pass audit

## Result

The shared ledger records exactly two full 047 retrieval-evaluation passes with
`call_kind="rerank"`, which is within the B5-16 limit of three. No replacement
test run was performed after the frozen test result.

| Pass | Run | Trigger and frozen code point | Questions | Rerank calls | Result |
| --- | --- | --- | ---: | ---: | --- |
| 1 | `047-hybrid-dev-finance_v1-43f11085-heading_page_first_1024_256` | Dev-only parameter confirmation before freeze | 24 | 107 | Recall@20 0.10416666666666667; rerank nDCG@10 0.043490471214667724 |
| 2 | `047-hybrid-test-finance_v1-43f11085-heading_page_first_1024_256` | One frozen test execution after `d87e2b5` (`docs(rag): freeze hybrid evaluation parameters`) | 26 answerable test questions | 90 | Recall@20 0.01282051282051282; rerank nDCG@10 0.0; quality gate FAIL |

The ledger timestamps place the dev pass before the parameter-freeze commit and
the test pass after it. The test output remains a negative result under B5-5;
this count audit does not reinterpret it as a quality pass.

## Evidence boundary

The 107 and 90 figures are individual rerank provider calls, not evaluation
pass counts. B5-16 limits full evaluation passes; the unique evaluation run IDs
above establish that count. The raw shared ledger and the ignored per-pass JSON
outputs remain the source evidence.
