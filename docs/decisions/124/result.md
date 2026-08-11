# 124 result

R121 gave the loop a working second pass and it retrieved nothing. This round
found out what that pass was doing, fixed it, and re-ran. It still retrieves
nothing — but the reason is now a property of the questions rather than a defect
in the refinement.

## What the second pass was searching for

R121's live Q13 state records both iterations' queries:

```
iteration 1
  [module_shipments_2024] 隆基绿能 2024年度 组件出货量 年报
                          晶科能源 2024年度 组件出货量 年报
  [profitability_2024]    隆基绿能 2024年年报 营业收入 归母净利润
  [shipment_caliber]      隆基绿能 出货量 统计口径 组件 硅片 电池片

iteration 2
  [module_shipments_2024] 研究主体 事项 公告
                          研究主体 事项 报告
  [shipment_caliber]      研究主体 事项 报告
                          研究主体 事项 公告
```

Four of the six refined queries name **no entity, no metric and no period**.
`研究主体` and `事项` are placeholders — "research subject" and "matter" — and
they were sent to a live search engine, spending the branch budget R121 had just
rationed for the second iteration.

The placeholder was deliberate. `build_replan_query` refuses to fall back to a
sub-question's prose, so a plan with no `structured_data_requests` assembles a
query out of no fields, and a comment records the intent: keep it "visibly
low-specificity". The intent was reasonable and the query was still issued. A
field assembly with no fields is not a low-specificity query, it is an absent
one.

## The fix

Two changes, in the order the constraint requires:

1. **Borrow terms from the planner, never from the title.** A sub-question's
   `search_queries` are already field assemblies that passed the planner's own
   validation, carrying issuer, metric and period. Where a structured request is
   absent, the refinement draws from them. The prose title is still never read,
   and the existing title-overlap guard still applies.
2. **A refinement that still names nothing is not issued.**
   `ReplanQueryUnavailable` tells the caller to drop it, and the count of
   dropped branches is recorded in the replan decision.

The title-overlap guard also had to stop crashing the graph. Borrowed terms can
echo the title, which that guard exists to refuse; refusing is right, ending the
run over it is not, so a borrowed assembly that trips it becomes an absent query.
A *structured* request that trips it is a real defect and still raises.

Q13's second pass now searches:

```
隆基绿能 公司 营业收入 归母净利润 扣非净利润 毛利率 20241231 公告
晶科能源 公司 营业收入 归母净利润 扣非净利润 毛利率 20241231 发布
隆基绿能 公司 晶科能源 公司 营业收入 归母净利润 扣非净利润 毛利率 20241231 年报
```

## Three configurations, same two questions

| configuration | Q | evidence | passes | gold in evidence | gold in report |
|---|---|---:|---:|---:|---:|
| loop off (R120 arm A) | Q13 | 61 | 0 | 1/2 | 1/2 |
| loop off (R120 arm A) | Q16 | 152 | 0 | 4/4 | 1/4 |
| loop on, placeholder queries (R121) | Q13 | 47 | 2 | 1/2 | 1/2 |
| loop on, placeholder queries (R121) | Q16 | 130 | 1 | 4/4 | 2/4 |
| **loop on, queries name things (R124)** | Q13 | 56 | 2 | 1/2 | 1/2 |
| **loop on, queries name things (R124)** | Q16 | 98 | 2 | 4/4 | 0/4 |

Cost CNY 0.79 against a 5.00 breaker.

## The answer, and why it is now believable

**A second research pass adds no gold fact on this sample**, and after this round
that is a statement about the questions rather than about broken machinery:

* Q16's four gold figures are **already retrieved in the first pass** — 4/4 in
  every configuration. There is nothing for a second pass to find. Its loss is
  downstream, in what the report says, which is R116's territory.
* Q13's missing figure is a single negative net-profit value that neither pass
  retrieves, including one now searching by issuer, metric and period.

That is consistent with everything measured since R116: the dominant loss is
selection, not retrieval, and R119 fixed the one genuine retrieval failure the
golden set contained. **The loop is mechanically sound and the remaining gaps
are not retrieval-shaped.**

Per R120's preregistered rule — strictly more gold tokens on both questions —
the default **stays closed**. It is closed on evidence now, not on a defect.

The `gold in report` column moves in every direction across runs (1/4, 2/4, 0/4
for the same question on near-identical code). That is the run-to-run variation
R118 measured, and no conclusion is drawn from it.

## Gate

```
Ran 1172 tests in 59.897s
OK (skipped=7)
[tracked_files_unchanged] gate created no tracked changes
gate_exit=0
```

An earlier run was red on four pre-existing tests, all with fixtures whose
sub-questions carry no structured request. The first version of this change
refused a refinement for that entire class, which was too blunt and is why the
planner-term fallback exists.

## Not established

- **That the loop never helps.** Two questions is not the golden set. What is
  established is that on the cases where it was most plausible, the gaps are not
  ones more searching closes.
- **Q13's missing figure.** A negative net profit that four live passes across
  three configurations did not retrieve.
