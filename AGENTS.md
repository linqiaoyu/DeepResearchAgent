# AGENTS.md

This repository is designed for a single Codex working loop. Treat this file as the operating contract for Codex-style work on DeepResearchAgent.

## Project Mission

DeepResearchAgent is a multi-agent deep research framework focused on:

- Planner, Researcher, Extractor, Critic, Reporter, and Evaluator workflow.
- Evidence Store with claim-source traceability.
- Citation verification and critic feedback loops.
- Long-horizon checkpoint recovery.
- Evaluation harness with quality, cost, latency, token, and bad-case metrics.

The project is resume/demo oriented, but implementation choices should still be explainable as production-minded engineering decisions.

## Single-Agent Working Loop

One Codex agent owns each iteration end to end. Do not use `.agent_handoff`-style handoffs, do not split work into Architect and Executor roles, and do not expand a task into unrelated modules.

Every iteration should:

1. Read the current repo state.
2. Choose one smallest verifiable task.
3. Implement only that task.
4. Run the relevant tests or smoke commands.
5. Self-review the change:
   - Did this make the project more production-minded?
   - Is there toy/demo-only risk?
   - Did it preserve deterministic MVP behavior?
   - Did it avoid scope creep?
   - How would this design be explained in an interview?
6. Report what changed, what was tested, whether it passed, residual risk, and the next smallest task.
7. Commit or push only after the task is stable and the user asks for it.

The product itself remains a multi-agent research workflow. Planner, Researcher, Extractor, Critic, Reporter, and Evaluator are domain components, not separate Codex development roles.

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
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
```

Run deterministic demo:

```bash
PYTHONPATH=src .venv/bin/python scripts/run_demo.py
```

Run evaluation sweep:

```bash
PYTHONPATH=src .venv/bin/python scripts/run_eval.py --limit 5
```

Run no-dependency fallback UI/API:

```bash
PYTHONPATH=src .venv/bin/python scripts/dev_server.py --port 8765
```

Create or refresh the local runtime with Python 3.11 or 3.12:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
```

With dependencies installed:

```bash
.venv/bin/uvicorn deepresearch_agent.api.main:app --host 0.0.0.0 --port 8000
.venv/bin/streamlit run ui/app.py
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
