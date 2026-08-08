# 092 result

Two independent defects from R091's live measurement. One is fixed and shown
live; the other is not, and the reason is worth more than the attempt.

## B: analysis now reaches the reader — fixed

`ReporterAgent._render_llm_report` kept a `detailed_analysis` claim only if it
shared evidence or a fact key with a key finding. When every key finding comes
from the structured provider and the analysis cites filing text, the two can
never share an evidence id, so R091 delivered four authored claims and zero
analysis lines.

Only in that case does citing the sub-question's own evidence stand in for the
missing signal; where a key finding does cite retrieved text the original rule
still applies, so off-topic claims still fall through to `补充事实`. Both
behaviours are pinned by tests, and reverting the change fails the new one with
the exact R091 output (`## 补充事实` holding the analysis).

Live result: `## 详细分析` appears in a delivered package for the first time,
`reader_analysis_lines` 0 → 1, `llm_authored_claims` 4 → 5.

## A: bounding the extractor in the schema — did not work

`ExtractedClaims` now declares `maxItems=12` and `extract_text` `maxLength=300`,
and the offline guard prices the worst case those permit at 6213 tokens against
an 8192 cap. The extractor still returned exactly 8192 tokens with
`finish_reason=length`.

Cause: `LLMClient.complete` passes the schema as *advisory text* -- it appends
`model_json_schema()` to a system message -- and the configured provider has no
strict-schema response format. The model is free to ignore `maxItems`, and did.
The schema bound is still worth keeping: it makes an over-long response a
`schema_violation`, which the repair path can fix, rather than a silent
oversize. But it is not a bound.

This retires a whole class of fix for this provider: no limit expressed only in
the request can constrain the response. The remaining levers act on the input or
on the response after it arrives.

## Cost

One paid run, CNY 0.078569, inside the CNY 0.5 per-run breaker. The round
stopped there rather than spending a second run on an unchanged cause.

## Still open, by line

- **INCOMPLETE (high)**: the extractor truncates at 8192 regardless of the
  schema. `src/deepresearch_agent/agents/extractor.py` `_llm_prompt_sources`
  sends up to 8 sources and 12,000 characters in one call, so the response
  scales with the whole retrieved set. Bounding the input per call is the
  lever that does not depend on model compliance.
- **INCOMPLETE (high)**: a truncated response is discarded whole.
  `LLMClient._parse_schema` rejects the payload, so eleven complete claims
  followed by one incomplete one yield nothing. Salvaging the valid prefix
  turns a total loss into a partial success and needs no provider cooperation.
- **INCOMPLETE (medium)**: `orphan_footnotes=6`, unchanged from R090/R091.
