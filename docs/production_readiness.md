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
| Evidence integrity | Done | Extract validation plus persisted Reporter footnote mapping; Evaluator and audit export do not infer from Evidence order | Real-LLM citation quality remains a separate judge task |
| Context overflow governance | Partial | Same-URL/different-extract collapsing is fixed; enabled fixture replay retained 12/21 finance and 13/29 wealth Evidence; footnote-contract repair restores both citation checks to 1.000; `CONTEXT_PACKER_ENABLED=false` | Run a budgeted real-LLM controlled comparison before activation; fixture cannot establish quality |
| Structured business output | Done on the deterministic default path | Pydantic comparison/timeline/risk objects and deterministic Markdown/JSON/XLSX renderers; `STRUCTURED_OUTPUT_ENABLED=true`; classified `additive_content` after two-topic equivalence proof | Validate additive behavior in LLM mode in 014; immediately return the flag to false if prose changes |
| Audit bundle export | Done for offline workflow | `scripts/export_audit_bundle.py` preflight checks citation closure; deterministic USD values are explicitly simulation estimates and CNY/provider billing is not claimed | Add archive signing, retention, and access control before regulated distribution |
| Research snapshot/change tracking | Done for offline workflow | Independent `ResearchSnapshot`; manifest-aware six-category diff; separate normalized/display keys, material-first deterministic Markdown/JSON/paste summary | Select durable version storage and analyst review UI before multi-user service use |
| Progressive delivery | Partial | `PROGRESSIVE_DELIVERY_ENABLED=false`; demo polling exposes ordered sections and validates byte-identical reassembly/citation closure | Reporter still generates atomically; true chapter generation needs a separately characterized LLM design |
| Decision auditability | Partial | `AgentDecision` has trace, manifest, and report landing points | Concrete sufficiency, memory, arithmetic, and skill-selection policies are not implemented |
| Trajectory replay | Partial | `TRAJECTORY_RECORD_ENABLED=false`; deterministic two-topic strict report replay, cache-miss stop, six-field and redaction tests | Record one authorized real run and validate LLM replay behavior before activation |
| MCP / skill packs | Not done | Design documents only; no runtime server or loader | Implement and test in a later bounded task |
| Configuration validation | Done | `CONFIG_FAIL_FAST_ENABLED=true`; fixture no-key and missing-provider-key tests | Keep the provider requirement matrix current as integrations change |
| Secrets | Partial | `.env` discipline, gitignore, log/manifest redaction utility | External secret manager and credential rotation for hosted operation |
| Data governance | Partial | Frozen Golden metadata, corpus fingerprint, read-only validation | Retention/deletion policy, source license register, data owner |
| Deployment | Partial | Non-root multistage Dockerfile, health/readiness routes, CI | Docker/Compose engine validation was unavailable on the development host; add image scan and signed release |
| Graceful shutdown | Partial | FastAPI lifespan stops readiness and waits for in-flight requests | Durable queue drain and cancellation semantics for background jobs |
| Disaster recovery | Not done | SQLite files/checkpoints exist locally | Backups, restore drill, RPO/RTO after a durable deployment is selected |
| Compliance | Not done | Research-only disclaimer and threat model | Legal review, privacy impact assessment, financial suitability controls before end-user investment use |
| SLO monitoring | Partial | Targets and 30 saved-state end-to-end generation measurements in `docs/slo.md`; role-level LLM sums are not independent workflow phase traces | Add phase traces and rolling service telemetry only with a long-running service |
| Human approval | Not done | No HITL workflow | Add only if the product scope includes high-impact publication or trading actions |
| Postgres/vector retrieval | Not done | Schema design only for Postgres; no vector store | Trigger on measured SQLite/search scaling limits, not portfolio optics |

## Remaining dark controls

1. Keep the context packer dark: positional-footnote confounding is fixed, but fixture quality metrics still cannot establish real-LLM quality; a later task needs a preregistered, budgeted comparison.
2. Keep the injection guard dark until licensed real-page calibration meets a PM-approved false-positive boundary.
3. Validate the active tool-contract path against real providers in the provider-integration task; current evidence is intentionally offline.
4. Keep trajectory recording dark until an authorized real trajectory validates full LLM replay and retention handling.

Every activation requires comparable manifests, full offline tests, and an E2E behavior/quality review. Dark implementation is not counted as an active production control.
