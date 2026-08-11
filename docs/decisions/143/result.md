# R143 — Content security ingress H2

Status: COMPLETE. Content security is `H2-ready`; `INJECTION_GUARD_ENABLED` remains default-off pending the financial graduation experiment.

A single `ContentIngressGuard` now labels and evaluates Web, RAG, MCP, and Skill content. Web attacks are quarantined inside explicit untrusted-data boundaries so legitimate quoted evidence remains available; RAG chunks, MCP outputs, and Skill content with registered injection patterns are rejected before they can become evidence, tool observations, or executable capabilities.

The full checked-in attack corpus was exercised across all four ingress kinds: 172 attack/ingress cases, zero successes. Every decision has an `untrusted_external` trust label and stable `content-security:` locator. A safe annual-report source produced the same reader-visible evidence with the guard on and off.

Extractor and Skill events reach run state/activity; MCP rejections reach the bounded tool error and trajectory. No paid provider was called; cost was CNY 0.
