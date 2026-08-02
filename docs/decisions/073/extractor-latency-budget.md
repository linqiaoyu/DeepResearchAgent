# Extractor latency-budget decision

## Evidence

R072 supplied 22 sources to the extractor. The existing 48,000-character,
six-source prompt and an 8,192-token output allowance exhausted all three
60-second provider attempts without a response. The workflow correctly
stopped, but T8 delivery could not complete.

## Decision

The extractor receives at most 12,000 source-content characters, at most
4,000 from one source, and may generate at most 1,024 completion tokens.
This is a latency and bounded-cost contract for an extraction step, not a
change to the evidence set: complete sources still serve provenance checks,
deterministic fallback, and authoritative financial-table backfills.

The guard creates twenty 8k sources and proves that exactly three / 12k reach
the provider payload while all source provenance stays available. Mutating the
12k bound back to 48k must fail that guard. No provider is invoked in this
round; a new paid T8 run needs explicit authorization after this code change.
