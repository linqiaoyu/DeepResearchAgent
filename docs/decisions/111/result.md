# 111 result

R110 closed with four items marked "not established" and named the finance
symbol-resolution defect as the largest measured product gap. This round closed
all of them, and the completion bar was set as a live run rather than a code
review.

Two kinds of number appear below and they do not carry equal weight. Provider
outcomes — records returned, resolution failures, period slots covered — are
deterministic. Judge scores are not: R109 measured this instrument's noise floor
at 2.32× the between-arm spread, so a weighted score at n=3 settles nothing and
is not used to claim anything here.

## The defect I attributed wrongly twice

R109 measured the symptom precisely: 46 structured requests, 16 records, 30
symbol-resolution failures, and 0 records for two of three golden issuers across
8 of 8 live runs each. I first blamed a hardcoded three-entry issuer dictionary,
then a dead endpoint.

It was neither. The combined listing endpoint answers correctly and returns all
5,539 listings, resolving every golden issuer — in **25.2 seconds**, against the
provider's **15-second** call budget. A ten-second margin took out the
authoritative data path for most issuers, and nothing reported it as anything
but "no symbol".

The table now comes from the per-venue endpoints (3.3s and 3.8s) and is cached
with its provenance. Measured live on the same three frozen questions:

| | R109, 24 live runs | R111 |
|---|---|---|
| symbol resolution failures | 30 | **0** |
| Q02 structured records | 0 in 8 of 8 runs | 4 |
| Q03 structured records | 0 in 8 of 8 runs | 5 |
| period-slot completeness | 68.9% | **83.3%** |
| 2023 coverage | 35.1% | **100%** |

The lesson worth keeping is not the fix. It is that a timeout margin presented
itself for two rounds as a missing mapping, and only direct timing of the call
distinguished them.

## Three gaps that were about proof, not capability

- **Nine capabilities no run could prove.** They are decided when a run is
  assembled and have no unit of work to count, so they are now recorded as
  `composed` and reported as `active` — wired in, with nothing claimed about
  what they did. Unprovable count 9 → 0, verified on a live run.
- **A storage backend nothing exercised.** Three Postgres tests had skipped on
  every run since they were written. The new CI job would not have fixed that on
  its own — a job whose tests skip still passes — so a guard asserts that with a
  DSN configured, zero of them skipped.
- **An extension point nobody could afford.** `DomainPack` declares 51 methods
  and every implementation answered all 51. `BaseDomainPack` answers each with
  "this domain has no opinion"; a domain overriding **one** method now completes
  a workflow and inherits none of finance's vocabulary. Finance remains the only
  product domain.

## What changed in AGENTS.md, and why

Three rules were added, each from a measured failure rather than a principle:
an enabled capability must be provable from the run's own artifacts; an
instrument's fidelity must be declared before its numbers are cited; a
comparison must state its noise floor before its conclusion.

More consequentially, every rule now names the check that fails when it is
broken, or is marked judgement-only. This project has twice demonstrated why:
"真实运行" was written for about a hundred rounds while the evaluation
instrument was fixture-only, and "不手抄默认值" sat in section one while six
documentation statements contradicted the code through every gate. A rule with
no enforcement surface is a preference, and labelling it honestly is cheaper
than discovering it a hundred rounds later.

## Not established

- Segment-level revenue lines (`手机部件及组装业务收入`, `汽车相关业务收入`)
  are still uncovered: the structured provider does not publish them, and they
  live in the annual report's segment table, which the PDF path cannot parse —
  the extraction defect R109 diagnosed and R110 declined to fix on speculation.
- A second product domain. The cost of writing one is now measured at one
  method; nobody has written one.
- 27 of the 30 golden questions have still never run at real fidelity.
