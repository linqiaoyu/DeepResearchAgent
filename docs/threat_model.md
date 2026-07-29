# Threat model

## Scope and assets

Protected assets are source evidence and its provenance, prompts, model and tool outputs, provider credentials, run cost budgets, checkpoints, evaluation results, and public demo artifacts. The trust boundary begins where web pages, provider payloads, or model output enter the process.

## Attack surfaces and controls

| Surface | Risk | Implemented control | State |
| --- | --- | --- | --- |
| External page text | Prompt injection and role spoofing | `security/content.py::detect_injection` marks direct, multilingual, encoded, long-context, and role-spoof patterns; `wrap_untrusted` creates an explicit data boundary before Extractor prompts | Dark; held-in synthetic recall was 100.00%, but the corpus and rules are co-designed, so this is not a generalization estimate. The primary result is a 15.00% safe-control false-positive rate; `INJECTION_GUARD_ENABLED=false` remains the default |
| Evidence provenance | A sanitizer could alter quoted evidence | Detection only labels; `Source.content` and `Evidence.extract_text` remain verbatim | Implemented and tested |
| Tool output | Timeout, transient failure, silent degradation | Typed contracts, per-call run context, retry and external-request budgets, circuit breaker, timeout quarantine, and degradation events in `tools/reliable_execution.py` | Enabled; `TOOL_CONTRACT_ENABLED=true`; offline failure matrix plus bounded real-provider degradation evidence |
| Model output | Fabricated citations or schema violations | Existing Pydantic structured output validation, extract substring checks, Critic, and citation evaluation | Enabled on existing paths |
| Credentials and PII | Secret or personal data in logs/manifests | `security/content.py::redact` masks key-like strings, mainland China phone/ID patterns, and email | Utility implemented; log/manifest sinks adopt it in their stages |
| Cost | Retry storms or unbounded paid calls | LLM cost fuse plus run-scoped retry, search/fetch, authority, branch, and provider-call budgets | Enabled on default boundaries; paid experiments still require explicit authorization and preregistration |

## Injection policy: label, do not delete

Injection detection deliberately does not delete or rewrite page text. Deletion would mutate the evidence excerpt, break source-to-claim traceability, and conflict with the project requirement that claims map back to verbatim source text. When the guard is enabled, the original block is wrapped for the model, detected patterns are recorded on `Evidence`, confidence is reduced for high-risk content, and Critic emits an `injection_risk` issue.

This is a heuristic signal, not a security proof. A high score does not establish malicious intent, and a low score does not establish safety.

## Offline injection calibration

The 011 calibration expanded `tests/fixtures/injection_corpus.json` from 23 to
63 cases: 43 risky cases and 20 safe controls. It covers multilingual mixes,
short encoded payloads, Unicode/full-width variants, commands buried in long
text, quoted/role-spoof instructions, and harmless passages containing
security-sensitive keywords.

At the operational threshold `risk_score > 0`, the adjusted rules detected
43/43 risky samples for **100.00% held-in synthetic recall**. The corpus and
the detection rules are co-designed, so this result does not estimate
generalization to real pages and must not be presented as production recall.

The primary calibration result is that 3/20 safe samples were flagged: a
**15.00% false-positive rate**. Those false positives were a security-research
quotation of an injection phrase, documentation explaining a `SYSTEM:` marker,
and a layout-only HTML comment. A research Agent naturally encounters all
three content classes frequently. It is therefore unsafe to assume the real
false-positive rate would be below 15.00%; without licensed real-page
calibration, the operational false-positive pressure is more likely higher.
That result—not the held-in recall—is the hard reason the guard remains dark.

## Fetch policy

`FetchPolicy` makes domain blacklist, robots handling, response size, content type allowlist, and redirect limits explicit. Current adapters do not yet enforce every field: Tavily already limits retained raw content, while robots and redirect enforcement depend on a future first-party fetch adapter. The default object documents the boundary without claiming enforcement that does not exist.

## Residual risk and intentionally unimplemented work

- Novel, image-based, context-dependent, or unseen encoded/multilingual injections can evade pattern matching. A learned classifier was not added because this task forbids dependencies and API calls.
- Evidence is still exposed to deterministic extraction logic; the wrapper protects only model prompt assembly when explicitly enabled.
- Existing historical ledgers are not retroactively redacted.
- Robots and redirect controls are not wired into Tavily because the provider owns the underlying fetch. A future direct fetch adapter must enforce `FetchPolicy`.
- No content is automatically blocked or quarantined. Automated blocking could suppress legitimate counter-evidence and needs measured false-positive rates plus PM approval.
- No browser sandbox, malware scanning, DLP service, or human approval system is present.
