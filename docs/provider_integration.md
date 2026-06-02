# Optional Provider Integration

This document is the implementation contract for real provider work after the
deterministic MVP is stable. External providers must improve realism without
breaking local tests, CI, or the no-key demo path.

## Non-Negotiable Rules

- Deterministic MVP remains the default. A clean checkout must run without paid
  API keys.
- Real providers are opt-in through environment variables or explicit settings.
- Every provider adapter must have mock/fake tests that do not call the network.
- CI must keep running unittest, demo smoke, and eval baseline diff without
  external secrets.
- Public behavior changes must update README, `docs/architecture.md`, and
  `docs/evaluation.md` when metrics or commands change.
- Provider failures must fail closed to a clear error or fallback path; they must
  not silently corrupt Evidence Store attribution.

## Provider Roadmap

### Search: Tavily or Serper

Current boundary: `SearchProvider.search(query, top_k, source_type)`.

Implementation shape:

- Add a new adapter under `src/deepresearch_agent/tools/`.
- Return normalized `Source` objects with URL, title, source type, published date,
  content, and credibility.
- Keep `FixtureSearchTool` as the default in `DeepResearchEngine`.
- Select the real adapter only when an env var such as
  `DEEPRESEARCH_SEARCH_PROVIDER=tavily` and the matching API key are present.

Minimum tests:

- Adapter unit test with mocked HTTP responses.
- Engine injection test proving the workflow accepts the adapter through
  `SearchProvider`.
- No-key test proving the deterministic fixture path still runs.

Acceptance commands:

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
PYTHONPATH=src .venv/bin/python scripts/run_eval.py --limit 5 --compare-baseline
```

### LLM Agents: LiteLLM Planner or Reporter

Current boundary: deterministic agent classes with Pydantic schema contracts and
prompt files in `prompts/`.

Implementation shape:

- Add an optional LiteLLM-backed agent behind the same public method contract.
- Keep deterministic agents as defaults.
- Read prompts from `prompts/`; do not hard-code production prompts in business
  logic.
- Validate all LLM outputs through existing Pydantic schemas before they enter
  workflow state.

Minimum tests:

- Mock LiteLLM response test for schema-valid output.
- Malformed response test proving validation fails clearly.
- No-key test proving deterministic Planner/Reporter still run.

### Storage: Postgres Evidence Store

Current boundary: `SQLiteStore` methods used by the engine:
`save_checkpoint`, `load_checkpoint`, `add_evidence_many`, `list_evidence`,
`save_evaluation`, and `latest_metrics`.

Implementation shape:

- Add a Postgres store adapter without removing `SQLiteStore`.
- Use `docs/postgres_schema.sql` as the schema source of truth.
- Select Postgres only through explicit settings or env configuration.
- Preserve evidence IDs and `sub_question_id` attribution exactly across retry
  loops and checkpoint resume.

Minimum tests:

- Contract tests shared by SQLite and a mocked/fake Postgres adapter.
- Retry attribution tests must pass for any store implementation.
- No-Postgres CI path must remain green.

### Workflow Parity: LangGraph

Current boundary: `DeepResearchEngine.run(...)` and `ResearchState`.

Implementation shape:

- Treat LangGraph as parity work, not a rewrite of semantics.
- Preserve the same phases: planning, researching, extracting, critiquing,
  reporting, evaluating, done.
- Preserve checkpoint resume by `research_id`.
- Keep existing deterministic engine available until LangGraph passes the same
  contract tests.

Minimum tests:

- Phase parity test against the deterministic engine.
- Checkpoint resume test.
- Eval baseline diff on the deterministic fixture path.

## Rollout Checklist

Before merging any real provider adapter:

- Default no-key demo still uses deterministic fixtures.
- `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests` passes.
- `PYTHONPATH=src .venv/bin/python scripts/run_eval.py --limit 5 --compare-baseline` passes.
- New provider has mock tests and no live network calls in CI.
- README and docs clearly label the provider as optional.
- Public demo readiness checklist still states deterministic fixture, SQLite MVP,
  synchronous API, and optional provider backlog unless those gaps are actually
  closed.
