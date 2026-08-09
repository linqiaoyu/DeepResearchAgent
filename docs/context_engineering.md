# Context engineering

The context packer runs behind `CONTEXT_PACKER_ENABLED=true`, the default since Round 087's single-flag live A/B. Setting it to `false` restores the earlier path, which passes the complete evidence list to Reporter.

`ContextBudget` uses 200,000 tokens for Planner, Extractor, and Reporter, matching the current run-level token budget rather than introducing a tighter implicit limit. Reporter can be configured with `DEEPRESEARCH_REPORTER_CONTEXT_TOKEN_BUDGET` only when the packer is enabled.

Packing is deterministic:

1. normalize URL and hash verbatim extract text into a composite deduplication key;
2. rank with a weighted geometric score of credibility × relevance × freshness;
3. fill without exceeding the node budget;
4. return every dropped evidence id with `duplicate_url`, `duplicate_content`, `over_budget`, or `lower_rank`.

Default exponents are credibility 0.4, relevance 0.4, and freshness 0.2. Evidence confidence is the available credibility signal; lexical topic overlap is the relevance signal; freshness decays as `1 / (1 + age_days / 365)`. Equal scores retain input order. When enabled, the complete selection/drop decision is appended to the run's `context_events` and can be persisted in a run manifest.

The composite key is deliberate: multiple distinct extracts from one page are separate evidence. An item is dropped as `duplicate_content` only when both its normalized URL and verbatim extract hash match an earlier item. `duplicate_url` remains in the event schema for compatibility with previously recorded runs, but corrected packing does not emit it.

The token estimator first probes for an already installed `tiktoken`; otherwise a standard-library fallback counts each CJK character as one token and four other characters as one token. No tokenizer dependency is required.

Fixture characterization can detect packing changes but cannot, by itself,
measure the research quality of an Evidence-changing control. The reproduced
footnote-order failure and the resulting activation boundary are documented in
[`method_limits.md`](method_limits.md).
