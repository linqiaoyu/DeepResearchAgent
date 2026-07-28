# B8 real-provider run — INCOMPLETE

On 2026-07-28 the repository owner authorized up to three bounded live attempts.
All three credentials were present; a minimal `openai/qwen3.7-plus` judge call
succeeded. Total estimated LLM cost, including the probe, was 0.10164388 CNY.

Attempt 1 used real LLM, Tavily, and CNINFO, but AKShare `symbol_resolve` failed
within its existing bounded retry policy and recorded a degradation event. Attempt
2 stopped at the reporter's mechanical Evidence fidelity contract. Attempt 3
completed with real LLM/judge/CNINFO, but its trajectory did not actually invoke
AKShare despite the request asking for the comparison.

The required three-layer evidence is therefore absent. This decision records B8
as INCOMPLETE; it does not infer numerical correctness from a completed pipeline.
The DASHSCOPE credential should be rotated because it was exposed in conversation;
no credential characters are retained here.
