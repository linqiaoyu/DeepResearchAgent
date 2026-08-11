"""R121: a pool that must cover N iterations may not be spent by the first.

R120 enabled the loop with `max_iterations=2` and no refinement pass ran on
either question. The recorded decisions gave the mechanism: `max_searches_per_run`
is 20, `research_loop_budget_ceiling` is 20, and
`decision_weaving_budget_remaining_ratio` is 0.2, so a first pass sized to spend
the pool ends either at the ceiling (Q13, 20/20) or under the ratio (Q16,
17/20 -> 0.15 remaining). A second iteration was reachable only if the first
used 15 or fewer of its 20 calls.
"""

from __future__ import annotations

import unittest

from deepresearch_agent.orchestration.budget import BranchBudget
from deepresearch_agent.schemas import ResearchState

class BranchBudgetIterationShareTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = ResearchState(topic="t")
        self.branches = ["a", "b", "c", "d"]

    def _allocate(self, planned: int) -> dict[str, int]:
        budget = BranchBudget(
            total_budget=20, per_branch_cap=10, planned_iterations=planned
        )
        return budget.allocate(self.branches, self.state)

    def test_a_single_iteration_still_gets_the_whole_pool(self) -> None:
        self.assertEqual(sum(self._allocate(1).values()), 20)

    def test_two_iterations_leave_half_the_pool_for_the_second(self) -> None:
        self.assertEqual(sum(self._allocate(2).values()), 10)

    def test_no_branch_is_allocated_nothing(self) -> None:
        for planned in (1, 2, 3, 4):
            with self.subTest(planned=planned):
                self.assertTrue(all(value >= 1 for value in self._allocate(planned).values()))

    def test_a_share_smaller_than_the_branch_count_is_raised_to_it(self) -> None:
        budget = BranchBudget(total_budget=4, per_branch_cap=10, planned_iterations=8)
        allocation = budget.allocate(self.branches, self.state)
        self.assertEqual(sum(allocation.values()), 4)
        self.assertTrue(all(value >= 1 for value in allocation.values()))

    def test_planned_iterations_must_be_at_least_one(self) -> None:
        with self.assertRaises(ValueError):
            BranchBudget(total_budget=20, per_branch_cap=10, planned_iterations=0)


# No end-to-end test lives here on purpose. One was written in fixture mode and
# deleted: forcing `planned_iterations` back to 1 -- the pre-R121 behaviour that
# R120 measured stopping the loop dead -- still produced two research passes,
# because a fixture branch is satisfied in fewer calls than either allocation
# grants, so the allocation never binds. It passed for both implementations,
# which makes it evidence of nothing, and shipping it would have been the
# fixture-instrument mistake R109 recorded. The arithmetic is tested above,
# where it discriminates; the end-to-end claim is settled by the live run in
# `docs/decisions/121/`.


if __name__ == "__main__":
    unittest.main()
