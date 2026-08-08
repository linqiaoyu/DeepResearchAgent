# 093 result

## Acceptance met

```
$ scripts/check_llm_agent_liveness.py artifacts/093/live-nio-zh
extractor_fallback=0 reporter_fallback=0 structured_parse_errors=0
truncated_calls=0 llm_authored_claims=5 reader_analysis_lines=2
orphan_footnotes=0                                            → exit 0
```

Every threshold this round was confirmed against is met, on one paid run of
CNY 0.103103. For comparison, the same command against the R087 delivery -- the
package the project had been treating as its finished product -- reads
`1 / 1 / 4 / 4 / 0 / 0 / 8`.

`orphan_footnotes` reaching 0 was not a target. It followed from the extractor
finally working: the reference list only ever held sources the evidence store
carried, and the store now holds what the model actually used.

## What made the difference

**One source per extractor call.** R090 raised the completion cap from 1024 to
4096, R091 to 8192, R092 declared `maxItems`/`maxLength` in the schema, and the
model filled every cap exactly, each time with `finish_reason=length`. R092
established why: `LLMClient.complete` passes the JSON Schema as advisory text
and this provider has no strict-schema response format, so nothing in the
request can constrain the response. Bounding the input does not need the model
to comply. Three calls, 4677 / 4090 / 1594 completion tokens, zero truncations.

The R073 budget is untouched -- 3 of 20 sources and 12,000 characters reach the
provider -- and the guard now asserts that across calls, which additionally
pins that no call carries more than one source.

**Salvaging a truncated response.** A response cut off inside an element used to
be discarded whole. `salvage_truncated_json` keeps the elements that closed
cleanly and shuts the brackets there, returning nothing when nothing complete
precedes the cut. It did not fire in this run -- there was nothing to salvage --
and it stays as the net for the case where an input bound is not enough. A
salvaged call is still counted as truncated, with a separate `salvaged_calls`
aggregate, so a partial result cannot read as a whole one.

## The delivered report

The reader now receives cited key findings, a derived gross margin, a
`## 详细分析` section grounded in the 20-F, five substantive limitations
(missing 2023 comparatives, no MD&A, no cost or delivery data, EDGAR-versus-
filing scope differences) and three cited unverified assumptions. Every listed
reference is cited in the body.

R087's delivery on the same question was thirteen lines carrying two numbers
from one structured API call, with eight uncited references.

## Still open, by line

- **INCOMPLETE (medium)**: the extractor's per-call cost is now 3 calls instead
  of 1 (CNY 0.103103 against R091's 0.078569 for a run that failed). Batching by
  token budget rather than one-source-per-call would recover some of that;
  `src/deepresearch_agent/agents/extractor.py` `_llm_extract`.
- **INCOMPLETE (medium)**: only 3 of 8 admitted RAG sources reach the provider,
  because R073's 12,000-character budget was written for a single call and is
  still applied to the whole extraction. Per-call bounding makes a larger total
  budget safe; the number should be revisited deliberately rather than
  inherited.
