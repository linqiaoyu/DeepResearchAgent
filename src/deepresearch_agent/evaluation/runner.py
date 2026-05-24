from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from deepresearch_agent.schemas import EvaluationResult
from deepresearch_agent.settings import project_root
from deepresearch_agent.workflow import DeepResearchEngine


class EvaluationHarness:
    def __init__(self, engine: DeepResearchEngine | None = None, eval_path: Path | None = None) -> None:
        self.engine = engine or DeepResearchEngine()
        self.eval_path = eval_path or project_root() / "data" / "eval_set.jsonl"

    def load_cases(self, limit: int | None = None) -> list[dict]:
        cases: list[dict] = []
        with self.eval_path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                cases.append(json.loads(line))
                if limit and len(cases) >= limit:
                    break
        return cases

    def run(self, limit: int | None = 5) -> dict:
        results: list[EvaluationResult] = []
        for case in self.load_cases(limit=limit):
            state = self.engine.run(topic=case["topic"], depth_level=case.get("depth_level", 2))
            if state.evaluation:
                results.append(state.evaluation)
        if not results:
            return {}
        bad_case_categories = Counter()
        for result in results:
            bad_case_categories.update(result.bad_case_categories)

        return {
            "cases": len(results),
            "avg_task_success_rate": round(sum(r.task_success_rate for r in results) / len(results), 3),
            "avg_citation_accuracy": round(sum(r.citation_accuracy for r in results) / len(results), 3),
            "avg_critic_catch_rate": round(sum(r.critic_catch_rate for r in results) / len(results), 3),
            "avg_answer_relevance": round(sum(r.answer_relevance for r in results) / len(results), 3),
            "avg_faithfulness": round(sum(r.faithfulness for r in results) / len(results), 3),
            "avg_latency_seconds": round(sum(r.latency_seconds for r in results) / len(results), 3),
            "avg_cost_usd": round(sum(r.cost_usd for r in results) / len(results), 4),
            "avg_token_used": round(sum(r.token_used for r in results) / len(results), 3),
            "bad_case_categories": dict(bad_case_categories),
        }
