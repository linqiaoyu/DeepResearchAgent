# AGENTS.md

This repository is designed for a two-agent collaboration model. Treat this file as the operating contract for Codex-style work on DeepResearchAgent.

## Project Mission

DeepResearchAgent is a multi-agent deep research framework focused on:

- Planner, Researcher, Extractor, Critic, Reporter, and Evaluator workflow.
- Evidence Store with claim-source traceability.
- Citation verification and critic feedback loops.
- Long-horizon checkpoint recovery.
- Evaluation harness with quality, cost, latency, token, and bad-case metrics.

The project is resume/demo oriented, but implementation choices should still be explainable as production-minded engineering decisions.

## Agent Roles

### Architect Agent

The Architect Agent plans, reviews, and audits. It should:

- Convert product/career goals into explicit implementation tasks and acceptance criteria.
- Keep scope aligned with the PDF-derived plan: Evidence Store, Critic, Evaluation Harness, checkpointing, API/UI, docs, and deployment.
- Review Executor Agent outputs for correctness, maintainability, demo readiness, and interview defensibility.
- Prefer comments, review notes, checklists, and follow-up tasks over direct code edits.
- Avoid mutating implementation files unless the user explicitly asks the Architect Agent to implement or repair something.

### Executor Agent

The Executor Agent implements. It should:

- Follow the Architect Agent's task spec and avoid adding unrelated modules.
- Keep changes small enough to review.
- Run the relevant tests before handing work back.
- Update docs when public behavior, commands, APIs, or evaluation outputs change.
- Preserve the local deterministic MVP unless replacing a component with a fully tested real integration.

## Review Gates

Use these gates before considering a milestone complete:

- Gate 1: Project skeleton contains `pyproject.toml`, Docker assets, `.env.example`, `src/`, `tests/`, `docs/architecture.md`, and `docs/evaluation.md`.
- Gate 2: MVP runs from a topic to a Markdown report with source-backed citations.
- Gate 3: Evidence and Critic pass: key claims map to sources, and Critic detects missing citations, numeric conflicts, outdated sources, missing counterarguments, or unverified projections.
- Gate 4: Evaluation harness is runnable and reports citation accuracy, relevance, faithfulness, cost, latency, tokens, and bad-case categories.
- Gate 5: Release packaging is demo-ready with README, architecture diagram, Docker Compose, and deployment notes.

## Local Commands

Run tests:

```bash
PYTHONPATH=src python -m unittest discover -s tests
```

Run deterministic demo:

```bash
PYTHONPATH=src python scripts/run_demo.py
```

Run evaluation sweep:

```bash
PYTHONPATH=src python scripts/run_eval.py --limit 5
```

Run no-dependency fallback UI/API:

```bash
PYTHONPATH=src python scripts/dev_server.py --port 8765
```

With dependencies installed:

```bash
uvicorn deepresearch_agent.api.main:app --host 0.0.0.0 --port 8000
streamlit run ui/app.py
```

## Engineering Rules

- Default to deterministic local tests. Do not require paid API keys for CI or basic demos.
- Keep external providers behind tool/agent interfaces so Tavily, LiteLLM, LangGraph, and Postgres can be swapped in without rewriting workflow semantics.
- Do not commit `.env`, runtime databases, `artifacts/`, or generated caches.
- Use Pydantic schemas for cross-agent contracts.
- Keep prompts in `prompts/`, not hard-coded inside business logic, when moving from deterministic MVP to real LLM calls.
- Document any metric definition change in `docs/evaluation.md`.

## Scope Guardrails

Do not add new product areas until the core PDF-derived system is solid. Prefer finishing the current differentiators over adding new features:

- Evidence Store.
- Critic feedback loop.
- Citation verification.
- Checkpoint recovery.
- Evaluation Harness.
- Demo packaging and deployment path.

