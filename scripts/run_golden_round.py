from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

from deepresearch_agent.evaluation import (
    JudgeClient,
    aggregate_round_results,
    classify_bad_case,
    extract_report_claims,
    false_premise_failed,
    judge_sample_spread,
    median_judge_score,
)
from deepresearch_agent.llm import LLMClient
from deepresearch_agent.schemas import ResearchState
from deepresearch_agent.workflow import DeepResearchEngine


def main() -> None:
    args = _parse_args()
    _load_env(Path(args.env_path))
    questions = json.loads(Path(args.questions).read_text(encoding="utf-8"))["questions"]
    if args.limit:
        questions = questions[: args.limit]

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    work_dir = Path(args.work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    os.environ.update(
        {
            "DEEPRESEARCH_MODE": "llm",
            "DEEPRESEARCH_SEARCH_PROVIDER": "tavily",
            "DEEPRESEARCH_SEARCH_RECORDING_MODE": "replay",
            "DEEPRESEARCH_SEARCH_RECORDING_DIR": args.recording_dir,
            "DEEPRESEARCH_STRUCTURED_DATA_PROVIDER": "fixture",
            "DEEPRESEARCH_AS_OF": args.as_of,
            "DEEPRESEARCH_LLM_LEDGER_PATH": args.ledger_path,
            "DEEPRESEARCH_LLM_BUDGET_CNY": str(args.run_budget_cny),
        }
    )

    judge_client = JudgeClient(
        LLMClient(
            ledger_path=Path(args.ledger_path),
            budget_cny=args.judge_budget_cny,
        )
    )
    results: list[dict[str, Any]] = []
    structured_failures = 0
    for index, case in enumerate(questions, 1):
        qid = str(case["id"])
        started = time.perf_counter()
        case_dir = work_dir / qid
        case_dir.mkdir(parents=True, exist_ok=True)
        os.environ["DEEPRESEARCH_STORAGE_PATH"] = str(case_dir / "research.db")
        try:
            state = DeepResearchEngine().run(topic=case["topic"], depth_level=args.depth)
            (case_dir / "state.json").write_text(
                state.model_dump_json(indent=2),
                encoding="utf-8",
            )
            (case_dir / "report.md").write_text(state.final_report or "", encoding="utf-8")
            result = _score_case(
                round_id=args.round_id,
                index=index,
                case=case,
                state=state,
                judge_client=judge_client,
                judge_samples=args.judge_samples,
                started=started,
            )
        except Exception as exc:
            structured_failures += 1
            result = {
                "id": qid,
                "status": "error",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "latency_seconds": round(time.perf_counter() - started, 3),
            }
        results.append(result)
        _write_round(output_path, args.round_id, results, structured_failures)
        print(f"{qid}: {result['status']}", flush=True)

    _write_round(output_path, args.round_id, results, structured_failures)


def _score_case(
    *,
    round_id: str,
    index: int,
    case: dict[str, Any],
    state: ResearchState,
    judge_client: JudgeClient,
    judge_samples: int,
    started: float,
) -> dict[str, Any]:
    evidence = [_slim_evidence(item.model_dump(mode="json")) for item in state.evidence_store]
    report = state.final_report or ""
    samples = [
        judge_client.score(
            run_id=f"{round_id}-{case['id']}-judge-{sample_index + 1}",
            case=case,
            report=report,
            evidence=evidence,
        )
        for sample_index in range(judge_samples)
    ]
    median_score = median_judge_score(samples)
    claims = extract_report_claims(report)
    citation_result = judge_client.citation_support(
        run_id=f"{round_id}-{case['id']}-citation-support",
        claims=claims,
        evidence=evidence,
    )
    mechanical = _mechanical_metrics(state)
    fp_failed = (
        false_premise_failed(report, case.get("gold", {}).get("must_not_assert", []))
        if case.get("false_premise") is True
        else False
    )
    categories = classify_bad_case(
        median_score,
        citation_result.support_rate,
        false_premise_failed=fp_failed,
    )
    return {
        "id": case["id"],
        "order": index,
        "status": "done",
        "research_id": state.research_id,
        "topic": case["topic"],
        "type": case["type"],
        "difficulty": case["difficulty"],
        "false_premise": bool(case.get("false_premise", False)),
        "false_premise_failed": fp_failed,
        "source_count": len(state.sources),
        "evidence_count": len(state.evidence_store),
        "judge": {
            "samples": [_judge_score_payload(item) for item in samples],
            "median": _judge_score_payload(median_score),
            "spread": judge_sample_spread(samples),
        },
        "citation_support": {
            "claim_count": len(claims),
            "support_rate": citation_result.support_rate,
            "verdicts": [item.model_dump(mode="json") for item in citation_result.verdicts],
        },
        "mechanical": mechanical,
        "bad_case_categories": categories,
        "cost_cny": float(state.evaluation.cost_cny if state.evaluation else 0.0),
        "latency_seconds": round(time.perf_counter() - started, 3),
    }


def _write_round(
    output_path: Path,
    round_id: str,
    results: list[dict[str, Any]],
    structured_failures: int,
) -> None:
    payload = {
        "round_id": round_id,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "structured_failures": structured_failures,
        "structured_failure_rate": round(structured_failures / len(results), 4) if results else 0.0,
        "results": results,
        "summary": aggregate_round_results(results),
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _judge_score_payload(score: Any) -> dict[str, Any]:
    payload = score.model_dump(mode="json")
    payload["weighted_score"] = score.weighted_score
    return payload


def _mechanical_metrics(state: ResearchState) -> dict[str, Any]:
    if not state.evaluation:
        return {}
    return {
        "citation_resolution_rate": state.evaluation.citation_resolution_rate,
        "critic_catch_rate": state.evaluation.critic_catch_rate,
        "token_used": state.evaluation.token_used,
        "price_source": state.evaluation.price_source,
    }


def _slim_evidence(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "claim": item.get("claim"),
        "claim_type": item.get("claim_type"),
        "source_kind": item.get("source_kind"),
        "source_url": item.get("source_url"),
        "source_title": item.get("source_title"),
        "extract_text": str(item.get("extract_text", ""))[:1000],
        "numeric_fields": item.get("numeric_fields"),
    }


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Golden Set v1 evaluation round.")
    parser.add_argument("--questions", default="data/golden_set/v1/questions.json")
    parser.add_argument("--output", required=True)
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--round-id", required=True)
    parser.add_argument("--recording-dir", default="data/recordings/golden_v1")
    parser.add_argument("--ledger-path", default="_collab/006r3_recording-completion/round_llm_ledger.jsonl")
    parser.add_argument("--env-path", default=".env")
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--depth", type=int, default=1)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--judge-samples", type=int, default=3)
    parser.add_argument("--run-budget-cny", type=float, default=3.0)
    parser.add_argument("--judge-budget-cny", type=float, default=3.0)
    return parser.parse_args()


if __name__ == "__main__":
    main()
