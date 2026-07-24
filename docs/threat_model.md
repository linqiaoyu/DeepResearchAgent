# Threat model

## Scope and assets

Protected assets are source evidence and its provenance, prompts, model and tool outputs, provider credentials, run cost budgets, checkpoints, evaluation results, and public demo artifacts. The trust boundary begins where web pages, provider payloads, or model output enter the process.

## Attack surfaces and controls

| Surface | Risk | Implemented control | State |
| --- | --- | --- | --- |
| External page text | Prompt injection and role spoofing | `security/content.py::detect_injection` marks common English/Chinese patterns; `wrap_untrusted` creates an explicit data boundary before Extractor prompts | Dark; `INJECTION_GUARD_ENABLED=false` by default |
| Evidence provenance | A sanitizer could alter quoted evidence | Detection only labels; `Source.content` and `Evidence.extract_text` remain verbatim | Implemented and tested |
| Tool output | Timeout, transient failure, silent degradation | Typed contracts, run retry budget, circuit breaker, and degradation events in `tools/reliable_execution.py` | Dark; `TOOL_CONTRACT_ENABLED=false` |
| Model output | Fabricated citations or schema violations | Existing Pydantic structured output validation, extract substring checks, Critic, and citation evaluation | Enabled on existing paths |
| Credentials and PII | Secret or personal data in logs/manifests | `security/content.py::redact` masks key-like strings, mainland China phone/ID patterns, and email | Utility implemented; log/manifest sinks adopt it in their stages |
| Cost | Retry storms or unbounded paid calls | Existing LLM budget plus run-level tool retry budget | LLM budget enabled; tool budget dark |

## Injection policy: label, do not delete

Injection detection deliberately does not delete or rewrite page text. Deletion would mutate the evidence excerpt, break source-to-claim traceability, and conflict with the project requirement that claims map back to verbatim source text. When the guard is enabled, the original block is wrapped for the model, detected patterns are recorded on `Evidence`, confidence is reduced for high-risk content, and Critic emits an `injection_risk` issue.

This is a heuristic signal, not a security proof. A high score does not establish malicious intent, and a low score does not establish safety.

## Fetch policy

`FetchPolicy` makes domain blacklist, robots handling, response size, content type allowlist, and redirect limits explicit. Current adapters do not yet enforce every field: Tavily already limits retained raw content, while robots and redirect enforcement depend on a future first-party fetch adapter. The default object documents the boundary without claiming enforcement that does not exist.

## Residual risk and intentionally unimplemented work

- Encoded, multilingual, image-based, or novel injections can evade pattern matching. A learned classifier was not added because this task forbids dependencies and API calls.
- Evidence is still exposed to deterministic extraction logic; the wrapper protects only model prompt assembly when explicitly enabled.
- Existing historical ledgers are not retroactively redacted.
- Robots and redirect controls are not wired into Tavily because the provider owns the underlying fetch. A future direct fetch adapter must enforce `FetchPolicy`.
- No content is automatically blocked or quarantined. Automated blocking could suppress legitimate counter-evidence and needs measured false-positive rates plus PM approval.
- No browser sandbox, malware scanning, DLP service, or human approval system is present.
