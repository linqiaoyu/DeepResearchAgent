# Interview Q&A

## How is this different from a search wrapper?

Search wrappers return pages and summaries. This project persists claim-level evidence, runs a Critic over citations, numeric conflicts, source age, and counterarguments, and exposes evaluation metrics for quality/cost/latency.

## Why use an Evidence Store?

Vector retrieval is good for recall, but it is weak as an audit log. Evidence Store rows connect every claim to a source URL, title, date, extract, and confidence. That makes citation verification and bad case analysis inspectable.

## What prevents the Critic from looping forever?

The engine uses `DEEPRESEARCH_MAX_CRITIC_ITER`, retry queues, and forced pass with visible warnings. The report does not hide unresolved issues.

## How is citation accuracy calculated?

The current deterministic metric checks whether every `[^n]` marker maps to an Evidence Store entry. A production version should add claim-source semantic verification with an LLM judge and spot human labels.

## What would you improve next?

Replace fixture search with Tavily/Serper, add real web fetch, add Postgres, wire LangGraph checkpointers, and run CI metric diffs over the 50-case golden set.

