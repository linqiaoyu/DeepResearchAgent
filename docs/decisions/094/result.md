# 094 result

## The target: web search was refused by this harness, not by the provider

`TavilySearchProvider` compared its credit threshold against the entire
append-only ledger. Cumulative credits reached the 520 cap on 2026-08-03, and
from then on every search was refused before leaving the process: 12 of 12 in
the R093 run, zero credits, zero results. The run manifest reported only
`search results unavailable; downstream evidence coverage may decrease`, which
reads as a provider outage.

Consequence: from R086 to R093 every "real" run was document QA over one frozen
60-document corpus plus one structured API call. The agent could not look
anything up, and nothing in any deliverable said so.

### Fixed

- Credits count per budget id, one per provider instance, so a run is bounded by
  its own spend. The lifetime ledger stays the audit record and stops being a
  gate. Thresholds are 20/30, sized for a run.
- A refusal names itself: `TavilySearchError` carries `refused_by` and
  `DegradationEvent` propagates it, so a self-refusal can no longer be reported
  as a provider outage.
- Counter-examples, both saved: restoring lifetime scope reproduces the exact
  production state (`used=520 hard_threshold=30`); removing the identity leaves
  the refusal anonymous.

### Verified live

```
round 094 searches: 4   refused: 0   credits: 4
degradation_events: []
evidence total: 8   web-sourced: 6
```

Zero degradation events for the first time in the rounds on record, and the
evidence store carries six claims from a source the agent found by searching --
NIO's Chinese annual report on HKEX, which the frozen corpus does not contain.

## What the fix exposed, in the same round

The first live run searched successfully and still delivered nothing new:
12 candidate sources, 3 admitted, 0 claims extracted. R073's 12,000-character
budget bounded one request back when one request carried every source; R093 made
each request carry a single source, after which that total only dropped
candidates. With web search restored it became the binding constraint. The
run-level bound is now a source count, and the guard states R073's actual goal
directly: no request carries more than one source or more than 4,000 characters.

Second run: `llm_context_source_count` 3 → 10, extractor claims 0 → 21, evidence
2 → 8.

`salvaged_calls: 1` -- R093's truncation salvage fired in production for the
first time and kept a cut-off response out of the fallback path.

## Not met, and why the round stops here

```
extractor_fallback=0 reporter_fallback=0 structured_parse_errors=1
truncated_calls=1 llm_authored_claims=0 reader_analysis_lines=0
orphan_footnotes=6
reporter finish_reason=length completion_tokens=8192 truncated=True salvaged=True
```

The reporter's response scales with the evidence set. Two evidence items fit in
8192 tokens; eight do not. Salvage kept the response out of the fallback path
but the cut landed before the authored claims, so the reader received none.

This is the extractor's problem one stage later, and the extractor's answer does
not transfer: the reporter must synthesise across all evidence and cannot be
split per item. It needs a different bound -- fewer evidence entries per report
call, or a two-stage report -- and that is a design choice, not a knob.

Two paid runs, CNY 0.085775 and CNY 0.195204, plus 4 Tavily credits. The round
stops before a third rather than spending it on an unchanged cause.

## Still open, by line

- **INCOMPLETE (high)**: the reporter truncates at 8192 on an 8-item evidence
  set. `src/deepresearch_agent/agents/reporter.py` `_llm_prompt_evidence` caps
  at 18 entries and 800 characters each, which bounds its input but not its
  output.
- **INCOMPLETE (medium)**: `invalid_extract_text=5` of 21 extracted claims --
  roughly a quarter of the model's verbatim spans did not match their source.
  First visible now that the LLM extractor runs on web sources.
- **INCOMPLETE (medium)**: `orphan_footnotes=6` returns whenever the reporter
  degrades, since the reference list is built from the evidence store rather
  than from what the body cites.
