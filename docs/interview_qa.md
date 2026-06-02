# Interview Q&A

## How is this different from a search wrapper?

Search wrappers return pages and summaries. This project persists claim-level evidence, runs a Critic over citations, numeric conflicts, source age, and counterarguments, and exposes evaluation metrics for quality/cost/latency.

## Why use an Evidence Store?

Vector retrieval is good for recall, but it is weak as an audit log. Evidence Store rows connect every claim to a source URL, title, date, extract, and confidence. That makes citation verification and bad case analysis inspectable.

## What prevents the Critic from looping forever?

The engine uses `DEEPRESEARCH_MAX_CRITIC_ITER`, retry queues, and forced pass with visible warnings. The report does not hide unresolved issues.

## How is citation accuracy calculated?

The current deterministic metric checks that each bullet citation marker maps to an Evidence Store entry, then verifies that the cited bullet claim has deterministic text overlap with `Evidence.claim` or `Evidence.extract_text`. Invalid or unsupported citations are counted under `bad_case_categories["citation_error"]`. A production version should add semantic claim-source verification with an LLM judge and spot human labels.

## Is critic_catch_rate a real recall metric?

No. In the MVP, `critic_catch_rate` is a deterministic heuristic/proxy for whether the Critic surfaced quality issues. Production recall should be computed from seeded issue sets or manually labeled bad cases.

## What would you improve next?

Keep fixture search as the deterministic default, harden the opt-in Tavily path with web fetch and quality evals, add Serper as another optional adapter, add Postgres, wire LangGraph checkpointers, and run CI metric diffs over the full 50-case golden set.
