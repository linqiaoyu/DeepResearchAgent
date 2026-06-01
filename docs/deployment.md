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
- Record a 1-2 minute demo showing Planner, Evidence Store, Critic retry, report, metrics, and checkpoint resume.

## Expected Verification Endpoints

After deployment, verify these public endpoints before marking the release live:

- API health: `/health`
- API metrics: `/metrics`
- UI: Streamlit app root

## Postgres Path

The MVP uses SQLite so it can run in a bare local environment. The production schema is in `docs/postgres_schema.sql`; swap `SQLiteStore` for a Postgres adapter when `psycopg` or SQLAlchemy is available.
