# Production readiness

Status vocabulary:

- **Done** means implemented and active on the stated default path.
- **Partial** includes implemented-but-dark controls or incomplete adapters.
- **Not done** means design only or absent.

The project remains an MVP and portfolio demo. Its public form is a static site, not a continuously operated research service.

| Area | Status | Evidence | Remaining work and trigger |
| --- | --- | --- | --- |
| Deterministic workflow reliability | Done | LangGraph fan-out/retry graph and SQLite checkpoint tests in `tests/integration/` | Load/concurrency testing before multi-user operation |
| Orchestration boundary contracts | Done | All graph nodes declare consumes, produces and invariants; decision nodes require a new `AgentDecision`; build/runtime violation tests cover four failure classes | Extend contracts whenever nodes or invariants change |
| Bounded research loop and branch budget | Partial | Native LangGraph back-edge, three loop bounds, run-scoped/per-branch allocation and deterministic replan tests; branch budget defaults on, multi-round loop defaults off | Keep the loop dark until a forced-insufficient real case exercises replan; keep monitoring default branch-budget behavior |
| Provider retry/circuit/degradation | Done | `TOOL_CONTRACT_ENABLED=true`; eight offline drills; per-call run context, independent authority budgets, bounded CNINFO retry and AKShare timeout quarantine | Successful four-layer real execution is proven, but real-provider failure payload coverage remains incomplete |
| Run-level token/cost guard | Done | LLM and external-request budgets are active; exhaustion checkpoints partial state and persists a schema-v4 `budget_exceeded` terminal trajectory/report artifact | Add a shared multi-provider monetary budget before more paid tools |
| Structured logging | Done | `STRUCTURED_LOGGING_ENABLED=true`; correlation/redaction and broken-sink tests | Add an external sink and retention policy only when a long-running service exists |
| Run lineage/comparability | Done | `RUN_MANIFEST_ENABLED=true`; all flags recorded; `tests/unit/test_run_manifest.py`; prompt guard active in CI | Define sidecar retention with the deployment storage lifecycle |
| Prompt injection handling | Partial | `security/content.py`, 63-case calibration in `docs/threat_model.md`, `INJECTION_GUARD_ENABLED=false` | The measured false positives and synthetic-only corpus require real licensed-page calibration and PM threshold approval |
| Evidence integrity | Done | Extract validation plus persisted Reporter footnote mapping; Evaluator and audit export do not infer from Evidence order | Real-LLM citation quality remains a separate judge task |
| Context overflow governance | Partial | Same-URL/different-extract collapsing is fixed; enabled fixture replay retained 12/21 finance and 13/29 wealth Evidence; footnote-contract repair restores both citation checks to 1.000; `CONTEXT_PACKER_ENABLED=true` since Round 087's budgeted live A/B | Evidence remains finance-SUT only; the packer's effect on other domains is unmeasured |
| Structured business output | Done on the deterministic default path | Pydantic comparison/timeline/risk objects and deterministic Markdown/JSON/XLSX renderers; `STRUCTURED_OUTPUT_ENABLED=true`; classified `additive_content` after two-topic equivalence proof | Validate additive behavior in an authorized LLM-mode task; immediately return the flag to false if prose changes |
| Audit bundle export | Done for offline workflow | `scripts/export_audit_bundle.py` preflight checks citation closure; deterministic USD values are explicitly simulation estimates and CNY/provider billing is not claimed | Add archive signing, retention, and access control before regulated distribution |
| Research snapshot/change tracking | Done for offline workflow | Independent `ResearchSnapshot`; manifest-aware six-category diff; separate normalized/display keys, material-first deterministic Markdown/JSON/paste summary | Select durable version storage and analyst review UI before multi-user service use |
| Progressive delivery | Partial | `PROGRESSIVE_DELIVERY_ENABLED=true` since Round 109, classified `operational`; demo polling exposes ordered sections and validates byte-identical reassembly/citation closure | Reporter still generates atomically; true chapter generation needs a separately characterized LLM design |
| Decision auditability | Partial | Immutable `DecisionContext` connects budget, sufficiency, prior classifications and Critic issues; decisions have trace, manifest and reader-visible chain landing points | Several policies remain dark; dynamic selection has real routing evidence but no measured quality gain |
| Numeric consistency | Partial | Critic deterministically checks growth, share, sum and unit conversions; failures carry claimed/calculated values, formula and Evidence IDs into retry | `NUMERIC_CHECK_ENABLED=true` since Round 087; real extraction scope/tolerance quality remains unvalidated |
| Research memory | Partial | Deterministic episodic and four-key semantic stores; context working-memory adapter; two-period prior behavior and confirmation-bias guard | In-process only; no durable adapter, forgetting policy, vector narrative retrieval or procedural memory |
| Capability registry | Partial beyond deterministic selection | Search, fetch, structured provider, disclosure, discovered MCP tools, and loaded skill capabilities share one registry; default deterministic selection records candidate/selected/rejected/fallback; optional LLM selection is default off | Round 033 proved route changes but no quality gain; LLM selection needs a controlled quality/cost comparison |
| Domain boundary | Partial productization | Core concrete-finance imports `0`; finance literals ratcheted to 3 files/9 lines; explicit finance DomainPack and deterministic NullDomainPack E2E | No second real domain pack; residual formatting/schema/audit literals remain under documented allowlist |
| Trajectory replay | Partial | Schema v4 persists typed completed/budget-exceeded/failed outcomes; legacy v3 remains load/validation-compatible; fixture coverage and Round 031 A4f verify fully offline, byte-identical replay of a completed real-LLM/structured/disclosure run | Noncompleted trajectories are audit artifacts and are not replayed; validate retention, access control, redaction lifecycle, and wider real-call coverage before activation |
| MCP / skill packs | Partial | Standard-library stdio server/client, four fixture tools, runtime registry discovery, metadata-first loader, one SHA-preserving finance rule pack, and strict fixture replay; see `docs/mcp.md` and `docs/skills.md` | Third-party full `tools/call` handshake is incomplete; add authenticated hosted transport and real-mode quality validation only under a later authorized task |
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
3. Expand real-provider failure coverage. Round 043 proved one LLM + Tavily +
   CNINFO + AKShare execution and several explicit degradation paths, but not a
   complete provider failure matrix.
4. Keep trajectory recording dark until retention, access-control,
   redaction-lifecycle, and noncompleted-trajectory operational handling are
   approved; completed real-LLM strict replay was validated in Round 031 A4f.
5. Keep multi-round research, prior-memory, decision weaving, numeric checking,
   reflection, skill loading, and LLM tool selection dark until their content
   and cost effects are measured. Branch budget and deterministic capability
   selection are already default-on and must remain covered by manifests and
   characterization gates.

Every activation requires comparable manifests, full offline tests, and an E2E behavior/quality review. Dark implementation is not counted as an active production control.
