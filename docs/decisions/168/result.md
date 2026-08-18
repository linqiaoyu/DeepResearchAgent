# R168 — DeepResearchHarness name harmonization

## Decision

**PASS.** The local project directory, GitHub repository, active project-facing name
references, and README clone instructions now use `DeepResearchHarness`.

The Python distribution and import package remain `deepresearch-agent` /
`deepresearch_agent`; evaluation questions, embedding fixtures, and historical decision
records were intentionally left unchanged. The external demo hostname was also left
unchanged because this round authorizes the project and repository name only.

## Remote and local state

- GitHub repository: `linqiaoyu/DeepResearchHarness`.
- GitHub default branch `main` points to the name-harmonization commit(s).
- The local `origin` URL uses the new repository name.
- The local directory basename is `DeepResearchHarness`.
- The task branch is `task/168-name-harmonization`.

## Verification

- `git diff --check`: PASS.
- Ruff across `src`, `tests`, and `scripts`: PASS.
- `scripts/check_agent_guidance.py --self-test`: PASS.
- `scripts/check_prompt_drift.py`: PASS; four changed prompts received patch-version
  bumps and new content hashes.
- The complete gate was attempted twice. The first attempt stopped at
  `check_capability_graduation.py --self-test` during a zero-CPU local Python module
  file read. After the environment recovered, the second attempt passed the initial
  guard, capability, finance-default, and Harness-acceptance checks, then stopped at
  `check_pairwise_composition.py --self-test` during another zero-CPU `langgraph`
  module read. Neither attempt produced a product assertion failure; the raw outputs
  and interrupts are retained in the round report.

No source package rename, evaluation-set edit, fixture rewrite, historical-record
rewrite, or unrelated remote write was performed.
