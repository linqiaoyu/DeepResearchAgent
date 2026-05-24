# Deployment

## Local

```bash
PYTHONPATH=src python scripts/run_demo.py
PYTHONPATH=src python -m unittest discover -s tests
```

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

## Postgres Path

The MVP uses SQLite so it can run in a bare local environment. The production schema is in `docs/postgres_schema.sql`; swap `SQLiteStore` for a Postgres adapter when `psycopg` or SQLAlchemy is available.

