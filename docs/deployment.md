# Deployment

Status: Public deployment is not yet completed. The steps below describe the
expected release path and verification checks after a public host is provisioned.

## Local

Use Python 3.11 or 3.12 and create a repo-local virtual environment:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
PYTHONPATH=src .venv/bin/python scripts/run_demo.py
PYTHONPATH=src .venv/bin/python scripts/run_eval.py --limit 5 --compare-baseline
PYTHONPATH=src .venv/bin/python scripts/run_checkpoint_demo.py
```

The deterministic MVP does not require external LLM or search API keys.

Expected local smoke signals:

- Demo: `phase=done status=done`
- Eval: `Baseline comparison:`, then `status: pass`
- Checkpoint demo: `paused_phase=critiquing paused_status=paused`, then `resumed_phase=done resumed_status=done`

## Docker Compose

```bash
docker compose up --build
```

Expected services:

- API: `http://localhost:8000`
- UI: `http://localhost:8501`

## Public URL Checklist

- Provision a small ECS or equivalent VM.
- Install Docker and Docker Compose.
- Copy repository and configure `.env`.
- Run `docker compose up -d --build`.
- Put Caddy/Nginx in front for HTTPS.
- Point `deepresearch.yulinqiao.com` to the host.
- Run the public smoke checklist below before sharing the URL.
- Record a 1-2 minute demo with the recording checklist below.

## Public Smoke Checklist

Use this after a public host is provisioned. Replace `BASE_URL` with the public
API origin and `UI_URL` with the Streamlit URL.

```bash
export BASE_URL=https://deepresearch.yulinqiao.com
export UI_URL=https://deepresearch-ui.yulinqiao.com

curl -fsS "$BASE_URL/health"
curl -fsS "$BASE_URL/metrics"
curl -fsS -X POST "$BASE_URL/research" \
  -H "Content-Type: application/json" \
  -d '{"topic":"AI Agent 在财富管理行业的落地机会研究","depth_level":2}'
```

Expected public smoke signals:

- `/health` returns `{"status":"ok"}`.
- `/metrics` returns JSON, even when no recent metrics exist.
- `POST /research` returns `status=done`, `current_phase=done`, a `research_id`, a `report_url`, and metrics.
- `GET /research/{id}` returns checkpointed state with non-empty `evidence_store`.
- `GET /research/{id}/report` returns Markdown with footnote-style citations.
- The Streamlit root opens and can run the same deterministic topic.

If the public smoke fails, keep the README/demo wording local-only until the
host is fixed. Do not present the public URL as live.

## Recording Checklist

Target length: 1-2 minutes. Show concrete outputs rather than explaining the
architecture verbally for too long.

1. Open README and point to the "not a generic RAG demo" differentiators.
2. Run `PYTHONPATH=src .venv/bin/python scripts/run_demo.py`.
3. Open the generated report and show footnote citations.
4. Run `PYTHONPATH=src .venv/bin/python scripts/run_eval.py --limit 5 --compare-baseline`.
5. Point to `Baseline comparison:` and `status: pass`.
6. Run `PYTHONPATH=src .venv/bin/python scripts/run_checkpoint_demo.py`.
7. Point to `paused_phase=critiquing paused_status=paused` and `resumed_phase=done resumed_status=done`.
8. If a public host is live, show `/health`, `/metrics`, and one `/research/{id}/report` response.

Recording acceptance criteria:

- Report shows source-backed citation markers such as `[^1]`.
- Evaluation shows citation accuracy, faithfulness, Critic catch rate, bad-case categories, cost, latency, and tokens.
- Checkpoint demo shows pause and resume in one command.
- No API keys or secrets appear on screen.
- Any production gaps are stated honestly: deterministic fixture search, SQLite MVP storage, synchronous API, and optional provider backlog.

## Expected Verification Endpoints

After deployment, verify these public endpoints before marking the release live:

- API health: `/health`
- API metrics: `/metrics`
- UI: Streamlit app root

## Postgres Path

The MVP uses SQLite so it can run in a bare local environment. The production schema is in `docs/postgres_schema.sql`; swap `SQLiteStore` for a Postgres adapter when `psycopg` or SQLAlchemy is available.
