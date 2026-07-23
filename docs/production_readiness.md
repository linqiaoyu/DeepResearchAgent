# Production readiness

Status vocabulary:

- **Done** means implemented and active on the stated default path.
- **Partial** includes implemented-but-dark controls or incomplete adapters.
- **Not done** means design only or absent.

The project remains an MVP and portfolio demo. Its public form is a static site, not a continuously operated research service.

| Area | Status | Evidence | Remaining work and trigger |
| --- | --- | --- | --- |
| Deterministic workflow reliability | Done | LangGraph fan-out/retry graph and SQLite checkpoint tests in `tests/integration/` | Load/concurrency testing before multi-user operation |
| Provider retry/circuit/degradation | Partial | `tools/reliable_execution.py`, `TOOL_CONTRACT_ENABLED=false` | Enable after provider error-rate baselines and manifest review |
| Run-level token/cost guard | Done/Partial | LLM budget is active; tool retry budget is dark | Add a shared multi-provider monetary budget before more paid tools |
| Structured logging | Partial | `observability/logging.py`, `STRUCTURED_LOGGING_ENABLED=false` | Enable with a log sink and retention policy |
| Run lineage/comparability | Partial | `provenance/manifest.py`, `RUN_MANIFEST_ENABLED=false`; prompt guard active in CI | Enable sidecars after storage lifecycle and PII review |
| Prompt injection handling | Partial | `security/content.py`, `INJECTION_GUARD_ENABLED=false`, `docs/threat_model.md` | Measure recall/false positives on real corpus before activation |
| Evidence integrity | Done | Extract substring validation and verbatim evidence tests | Add per-claim provenance beyond current evidence-to-report mapping |
| Context overflow governance | Partial | `context/packer.py`, `CONTEXT_PACKER_ENABLED=false` | Calibrate node budgets and quality impact before activation |
| Configuration validation | Partial | `config_validation.py`, `CONFIG_FAIL_FAST_ENABLED=false` | Enable in a deployment-specific entrypoint |
| Secrets | Partial | `.env` discipline, gitignore, log/manifest redaction utility | External secret manager and credential rotation for hosted operation |
| Data governance | Partial | Frozen Golden metadata, corpus fingerprint, read-only validation | Retention/deletion policy, source license register, data owner |
| Deployment | Partial | Non-root multistage Dockerfile, health/readiness routes, CI | Docker/Compose engine validation was unavailable on the development host; add image scan and signed release |
| Graceful shutdown | Partial | FastAPI lifespan stops readiness and waits for in-flight requests | Durable queue drain and cancellation semantics for background jobs |
| Disaster recovery | Not done | SQLite files/checkpoints exist locally | Backups, restore drill, RPO/RTO after a durable deployment is selected |
| Compliance | Not done | Research-only disclaimer and threat model | Legal review, privacy impact assessment, financial suitability controls before end-user investment use |
| SLO monitoring | Partial | Targets and saved measurements in `docs/slo.md` | No rolling service telemetry; commission only with a long-running service |
| Human approval | Not done | No HITL workflow | Add only if the product scope includes high-impact publication or trading actions |
| Postgres/vector retrieval | Not done | Schema design only for Postgres; no vector store | Trigger on measured SQLite/search scaling limits, not portfolio optics |

## Activation order for dark controls

1. Turn on run manifests in deterministic fixture runs; inspect redaction and comparability output.
2. Turn on structured logging to a temporary local sink; verify correlation and secret masking.
3. Turn on tool contracts for fixture/mock providers; inject failures and validate degradation reporting.
4. Calibrate context budgets offline, then enable the packer on comparable replay runs.
5. Measure injection guard recall/false positives on a licensed corpus before enabling it in LLM mode.
6. Enable fail-fast only in a deployment entrypoint with an explicit provider matrix.

Every activation requires comparable manifests, full offline tests, and an E2E behavior/quality review. Dark implementation is not counted as an active production control.
