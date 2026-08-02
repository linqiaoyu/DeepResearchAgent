# 083 result

## Numeric conclusion

Two of two authorized live runs passed `--require-structured` and the
fidelity probe: NIO recorded 2 structured records and PDD recorded 1. Their
total costs were CNY 0.05649468 and CNY 0.05964354 respectively, for CNY
0.11613822 across the round, below the CNY 20.00 ceiling.

Both manifests identify `SecCompanyFactsProvider`; each has
`sampled_numbers=1` and `verdict=PASS`. PDD also records the expected
`StructuredDataUnsupportedMetric` for the requested gross-margin ratio. This
is an explicit known limitation, not a covered ratio value.

The final domain-boundary measurement is `import_sites=0 literal_files=3
literal_hits=9 lexicon_terms=33`.
