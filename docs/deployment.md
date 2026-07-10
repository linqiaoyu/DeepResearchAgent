# Deployment

Status: 007 branch-B local release package. The public deployment step is
blocked until `.env` contains `DEPLOY_SSH_HOST`, `DEPLOY_SSH_KEY_PATH`,
`DEPLOY_PUBLIC_HOST`, and `DEMO_OWNER_TOKEN`. The local API/UI, demo assets,
daily spend guard, and runbook are ready for server execution.

## Demo Layers

- Showcase: `GET /demo`, `GET /demo/reports`, and the Streamlit Showcase tab
  serve curated G3 reports from `data/demo/g3_showcase.json`. This layer has no
  LLM, Tavily, AKShare, or judge calls.
- Golden rerun: `POST /demo/rerun/{question_id}` runs LLM mode over Golden Set
  frozen-corpus replay plus recorded structured-data fixtures. It uses
  `DEEPRESEARCH_AS_OF=2026-07-09` and consumes no Tavily credit.
- Owner live: `POST /demo/live` requires `X-Demo-Owner-Token` matching
  `DEMO_OWNER_TOKEN`, then runs free-form LLM mode with live Tavily search.

The paid layers share `DailyCostGuard`, persisted at
`DEEPRESEARCH_DEMO_GUARD_PATH` and capped by
`DEEPRESEARCH_DEMO_DAILY_LLM_LIMIT_CNY` (default `5.0`). When the cap is hit,
rerun and live endpoints return HTTP 429; the showcase remains available.
LangSmith tracing is enabled only when `LANGSMITH_API_KEY` exists.

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
Tavily search is optional: leave `DEEPRESEARCH_SEARCH_PROVIDER=fixture` for
CI/public demo stability, or set `DEEPRESEARCH_SEARCH_PROVIDER=tavily` plus
`TAVILY_API_KEY` only when intentionally making live search calls.

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

The image excludes `.env`, `_collab`, `artifacts`, local virtualenvs, runtime
databases, and caches through `.dockerignore`. Compose reads real secrets only
from an optional `.env`; `.env.example` is documentation, not a runtime secret
source.

Local smoke:

```bash
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:8000/demo
curl -fsS http://localhost:8000/demo/reports/Q16
curl -i -X POST http://localhost:8000/demo/live \
  -H "Content-Type: application/json" \
  -d '{"topic":"demo","depth_level":1}'
```

The unauthenticated live call should return HTTP 403 without printing any key
names or values.

## Public Runbook

All commands below must target only the host named by `DEPLOY_SSH_HOST`.

1. Provision a small ECS or equivalent VM. Security group inbound ports: `22`,
   `80`, `443` only.
2. Install Docker and Compose.

```bash
sudo timedatectl set-timezone UTC
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

3. Copy the repository to `/opt/deepresearch-agent` and create server-side
   `.env`. Do not echo secrets in logs.
4. Start the stack:

```bash
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 api
docker compose logs --tail=100 ui
```

5. Configure reverse proxy. If `DEPLOY_PUBLIC_HOST` is a domain, use automatic
   HTTPS, for example Caddy:

```text
DEPLOY_PUBLIC_HOST {
  reverse_proxy ui:8501
}
```

If only a bare IP exists, serve HTTP and keep the page labeled as a demo.

6. Verify restart policy and recovery:

```bash
docker compose restart
docker compose ps
docker kill deepresearchagent-api-1
sleep 10
docker compose ps
```

7. Configure log rotation through Docker daemon or host journald before sharing
   the URL.

## Public Smoke Checklist

Use this after a public host is provisioned. Replace `BASE_URL` with the public
API origin and `UI_URL` with the Streamlit URL.

```bash
export BASE_URL=https://deepresearch.yulinqiao.com
export UI_URL=https://deepresearch-ui.yulinqiao.com

curl -fsS "$BASE_URL/health"
curl -fsS "$BASE_URL/demo"
curl -fsS "$BASE_URL/demo/reports/Q16"
curl -i -X POST "$BASE_URL/demo/live" \
  -H "Content-Type: application/json" \
  -d '{"topic":"demo","depth_level":1}'
```

Expected public smoke signals:

- `/health` returns `{"status":"ok"}`.
- `/demo` returns the G3 summary and guard state.
- `/demo/reports/Q16` returns the false-premise showcase report.
- Unauthenticated `/demo/live` returns HTTP 403 without sensitive values.
- The Streamlit root opens, shows the curated reports, and can call the API.

Guardrail verification before making the URL public:

1. Set `DEEPRESEARCH_DEMO_DAILY_LLM_LIMIT_CNY=0` in server `.env`.
2. Restart Compose.
3. `POST /demo/rerun/Q01` must return HTTP 429.
4. `GET /demo/reports/Q01` must still return HTTP 200.
5. Restore the intended limit and restart.

AKShare server probe:

```bash
docker compose exec api python scripts/record_structured_data_fixture.py --help
```

Then run the three 005 capabilities against a disposable output path and compare
symbol resolve, financial indicators, and price history with
`data/mock_data/structured_finance.json`. If live AKShare is unstable, keep
`DEEPRESEARCH_STRUCTURED_DATA_PROVIDER=fixture` for the public demo and record
the difference in the deployment log.

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
- Any production gaps are stated honestly: deterministic fixture search by default, Tavily opt-in, SQLite MVP storage, synchronous API, and optional provider backlog.

## Expected Verification Endpoints

After deployment, verify these public endpoints before marking the release live:

- API health: `/health`
- Demo overview: `/demo`
- Showcase report: `/demo/reports/Q01`
- Guarded rerun: `/demo/rerun/Q01`
- Owner live search: `/demo/live`
- UI: Streamlit app root

## Rollback

```bash
git log --oneline -5
git checkout <previous-known-good-commit>
docker compose up -d --build
docker compose ps
curl -fsS "$BASE_URL/health"
```

Do not delete runtime ledgers during rollback. If a bad release consumed budget,
lower `DEEPRESEARCH_DEMO_DAILY_LLM_LIMIT_CNY` or set the guard file spent value
to the limit to disable paid layers while leaving the showcase online.

## Postgres Path

The MVP uses SQLite so it can run in a bare local environment. The production schema is in `docs/postgres_schema.sql`; swap `SQLiteStore` for a Postgres adapter when `psycopg` or SQLAlchemy is available.
