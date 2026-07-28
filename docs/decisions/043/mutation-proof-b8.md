# B8 mutation proof

Each mutation below was applied only long enough to run its named unit test, then
restored before the next check. These are raw unittest failures with local paths
removed.

## Criterion 3 — remove zero-record degradation

```text
E
ERROR: test_zero_record_execution_records_explicit_degradation
KeyError: 'degradation_events'
Ran 1 test in 0.063s
FAILED (errors=1)
```

## Criterion 4 — count executed request instead of records

```text
F
FAIL: test_zero_record_structured_call_is_not_real
AssertionError: 1 != 0
Ran 1 test in 0.006s
FAILED (failures=1)
```

## Criterion 5 — omit structured-data stats from manifest

```text
F
FAIL: test_manifest_records_structured_data_stats
AssertionError: {} != {'q': {'requests': 2, 'executed_requests': 2,
 'records': 1, 'symbol_resolution_failures': 0, 'execution_failures': 1}}
Ran 1 test in 0.007s
FAILED (failures=1)
```

## Criterion 6 — make renderer fidelity failure fatal

```text
E
ERROR: test_grounded_fact_fidelity_failure_degrades_without_raising
ValueError: test mutation: fidelity failure became fatal
Ran 1 test in 0.002s
FAILED (errors=1)
```
