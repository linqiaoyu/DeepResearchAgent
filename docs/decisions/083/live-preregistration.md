# 083 live-run preregistration

## Execution commitment

- Execution code commit: `cb1441d7b7c11ac2913223a54b18a515b306e0d4`.
- Both runs use that exact commit, with no parameter changes or reruns selected
  for outcome quality.
- As-of: `2026-07-01`; depth: `1`; structured provider:
  `SecCompanyFactsProvider` selected with
  `DEEPRESEARCH_STRUCTURED_DATA_PROVIDER=sec_companyfacts`.
- The three real layers are the configured LLM, live search, and SEC Company
  Facts. The live RAG service uses the registered finance index
  `finance_v1-43f11085-heading_page_first_1024_256` at
  `data/runtime/047-assets.db`.

## Hypothesis and measurement

The repaired selection path will create at least one SEC Company Facts request
and one structured record for each of the following fixed topics:

1. Chinese: `蔚来 2024 年年报的营收与毛利情况`.
2. English: `PDD 2024 annual report revenue and gross margin`.

Each package must pass `check_real_run_manifest.py --require-structured`, use
`SecCompanyFactsProvider` in the manifest, and pass the fidelity probe with
nonzero sampled numbers. The English run is expected to record the explicit
`StructuredDataUnsupportedMetric` limitation for gross margin while retaining
its isolated revenue request.

## Cost, abort, and rollback

- Maximum cost per run: CNY 15.00; maximum across the two runs: CNY 20.00.
- Stop immediately if either ceiling is reached. A failed run may be retried
  once, for at most three paid attempts total; otherwise record INCOMPLETE.
- If any real provider degrades to fixture, report the package as mixed and do
  not call it a real three-layer run.
- Rollback condition: a manifest/fidelity failure or budget trip preserves the
  package and evidence logs; no source rollback or extra paid run is made.
