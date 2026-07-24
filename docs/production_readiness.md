# Production readiness

Status vocabulary:

- **Done** means implemented and active on the stated default path.
- **Partial** includes implemented-but-dark controls or incomplete adapters.
- **Not done** means design only or absent.

The project remains an MVP and portfolio demo. Its public form is a static site, not a continuously operated research service.

| Area | Status | Evidence | Remaining work and trigger |
| --- | --- | --- | --- |
| Deterministic workflow reliability | Done | LangGraph fan-out/retry graph and SQLite checkpoint tests in `tests/integration/` | Load/concurrency testing before multi-user operation |
| Provider retry/circuit/degradation | Done | `TOOL_CONTRACT_ENABLED=true`; eight offline drills in `tests/chaos/test_tool_failures.py`; reader-visible degradation section | Real-provider behavior is not validated; exercise Tavily/provider errors before claiming that boundary |
| Run-level token/cost guard | Done | LLM budget and tool run retry budget are active | Add a shared multi-provider monetary budget before more paid tools |
| Structured logging | Done | `STRUCTURED_LOGGING_ENABLED=true`; correlation/redaction and broken-sink tests | Add an external sink and retention policy only when a long-running service exists |
| Run lineage/comparability | Done | `RUN_MANIFEST_ENABLED=true`; all flags recorded; `tests/unit/test_run_manifest.py`; prompt guard active in CI | Define sidecar retention with the deployment storage lifecycle |
| Prompt injection handling | Partial | `security/content.py`, 63-case calibration in `docs/threat_model.md`, `INJECTION_GUARD_ENABLED=false` | The measured false positives and synthetic-only corpus require real licensed-page calibration and PM threshold approval |
| Evidence integrity | Done | Extract substring validation and verbatim evidence tests | Add per-claim provenance beyond current evidence-to-report mapping |
| Context overflow governance | Partial | `context/packer.py`, `CONTEXT_PACKER_ENABLED=false`; 011 snapshots show evidence loss and a citation-accuracy regression on the pure-search topic | Fix same-URL multi-claim collapsing, then pass comparable replay quality gates |
| Configuration validation | Done | `CONFIG_FAIL_FAST_ENABLED=true`; fixture no-key and missing-provider-key tests | Keep the provider requirement matrix current as integrations change |
| Secrets | Partial | `.env` discipline, gitignore, log/manifest redaction utility | External secret manager and credential rotation for hosted operation |
| Data governance | Partial | Frozen Golden metadata, corpus fingerprint, read-only validation | Retention/deletion policy, source license register, data owner |
| Deployment | Partial | Non-root multistage Dockerfile, health/readiness routes, CI | Docker/Compose engine validation was unavailable on the development host; add image scan and signed release |
| Graceful shutdown | Partial | FastAPI lifespan stops readiness and waits for in-flight requests | Durable queue drain and cancellation semantics for background jobs |
| Disaster recovery | Not done | SQLite files/checkpoints exist locally | Backups, restore drill, RPO/RTO after a durable deployment is selected |
| Compliance | Not done | Research-only disclaimer and threat model | Legal review, privacy impact assessment, financial suitability controls before end-user investment use |
| SLO monitoring | Partial | Targets and saved measurements in `docs/slo.md` | No rolling service telemetry; commission only with a long-running service |
| Human approval | Not done | No HITL workflow | Add only if the product scope includes high-impact publication or trading actions |
| Postgres/vector retrieval | Not done | Schema design only for Postgres; no vector store | Trigger on measured SQLite/search scaling limits, not portfolio optics |

## Remaining dark controls

1. Keep the context packer dark until same-URL multi-claim handling is corrected and comparable replay shows no citation/quality regression.
2. Keep the injection guard dark until licensed real-page calibration meets a PM-approved false-positive boundary.
3. Validate the active tool-contract path against real providers in the provider-integration task; current evidence is intentionally offline.

Every activation requires comparable manifests, full offline tests, and an E2E behavior/quality review. Dark implementation is not counted as an active production control.
