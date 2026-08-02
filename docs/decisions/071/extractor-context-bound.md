# Extractor bounded-context decision

## Trigger

R071's real run supplied 28 retrieved sources to one extractor request. All
three 60-second provider attempts exhausted, even though planner, search,
embedding, and reranking succeeded. The full source body was previously
serialized without a bound.

## Decision

One extractor LLM request now accepts at most 48,000 source-content characters
and at most 8,000 characters from any individual source. Sources are selected
deterministically: primary tier first, then higher credibility, then their
original order. The bound applies only to text sent to the LLM. The full source
list remains available for provenance validation, deterministic extraction,
and authoritative financial-table backfill.

The extractor records selected, omitted, and content-character counts in its
stats. The guard creates 20 eight-kilobyte sources and asserts the provider
payload is exactly six sources / 48,000 characters. Mutation to an 80,000
character total fails the guard. Full gate passed after restoration.

## Consequence

This is a new code version. It reduces a bounded provider request rather than
changing provider timeout, retry, or budget semantics. A real T8 validation
must be preregistered and reauthorized.
