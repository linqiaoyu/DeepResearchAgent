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
    question_payload = json.loads(Path(args.questions).read_text(encoding="utf-8"))
    questions = _effective_questions(question_payload)
    if args.question_ids:
        requested = [item.strip() for item in args.question_ids.split(",") if item.strip()]
        requested_set = set(requested)
        available = {str(item["id"]) for item in questions}
        unknown = sorted(requested_set - available)
        if unknown:
            raise ValueError(f"--question-ids contains unavailable questions: {unknown}")
        questions = [item for item in questions if str(item["id"]) in requested_set]
    if args.limit:
        questions = questions[: args.limit]
    state_path_map = _load_state_path_map(Path(args.state_path_map)) if args.state_path_map else {}
    if state_path_map:
        _validate_saved_states(questions, state_path_map)
    if args.validate_only:
        print(
            json.dumps(
                {
                    "generation": args.generation,
                    "gold_version": question_payload.get("meta", {}).get("version"),
                    "effective_cases": len(questions),
                    "state_map": args.state_path_map,
                    "status": "available",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

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
    ledger_path = Path(args.ledger_path)
    round_ledger_start = _ledger_cost_cny(ledger_path)
    run_metadata = {
        "generation": args.generation,
        "gold_version": question_payload.get("meta", {}).get("version"),
        "evaluation_as_of": args.as_of,
        "judge_samples": args.judge_samples,
        "effective_question_ids": [str(item["id"]) for item in questions],
        "quarantined_question_ids": sorted(_quarantined_ids(question_payload)),
        "state_path_map": args.state_path_map or None,
    }
    results: list[dict[str, Any]] = []
    structured_failures = 0
    for index, case in enumerate(questions, 1):
        qid = str(case["id"])
        started = time.perf_counter()
        case_dir = work_dir / qid
        case_dir.mkdir(parents=True, exist_ok=True)
        os.environ["DEEPRESEARCH_STORAGE_PATH"] = str(case_dir / "research.db")
        case_ledger_start = _ledger_cost_cny(ledger_path)
        try:
            if (
                args.combined_budget_cny > 0
                and case_ledger_start + args.case_cost_reserve_cny > args.combined_budget_cny
            ):
                raise RuntimeError(
                    "combined judge ledger budget reserve would be exceeded: "
                    f"spent={case_ledger_start:.6f}, reserve={args.case_cost_reserve_cny:.6f}, "
                    f"budget={args.combined_budget_cny:.6f}"
                )
            if state_path := state_path_map.get(qid):
                state = ResearchState.model_validate_json(Path(state_path).read_text(encoding="utf-8"))
            else:
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
        result["judge_cost_cny"] = round(
            _ledger_cost_for_prefix(ledger_path, f"{args.round_id}-{qid}-"),
            8,
        )
        results.append(result)
        _write_round(
            output_path,
            args.round_id,
            results,
            structured_failures,
            run_metadata=run_metadata,
            round_judge_cost_cny=_ledger_cost_cny(ledger_path) - round_ledger_start,
        )
        print(f"{qid}: {result['status']}", flush=True)

    _write_round(
        output_path,
        args.round_id,
        results,
        structured_failures,
        run_metadata=run_metadata,
        round_judge_cost_cny=_ledger_cost_cny(ledger_path) - round_ledger_start,
    )


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
    *,
    run_metadata: dict[str, Any],
    round_judge_cost_cny: float,
) -> None:
    summary = aggregate_round_results(results)
    summary["total_judge_cost_cny"] = round(
        sum(float(item.get("judge_cost_cny", 0.0)) for item in results),
        8,
    )
    summary["round_ledger_cost_cny"] = round(round_judge_cost_cny, 8)
    payload = {
        "round_id": round_id,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        **run_metadata,
        "structured_failures": structured_failures,
        "structured_failure_rate": round(structured_failures / len(results), 4) if results else 0.0,
        "results": results,
        "summary": summary,
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _judge_score_payload(score: Any) -> dict[str, Any]:
    payload = score.model_dump(mode="json")
    payload["weighted_score"] = score.weighted_score
    return payload


def _mechanical_metrics(state: ResearchState) -> dict[str, Any]:
    if not state.evaluation:
        return {}
    reporter_stats = state.metadata.get("llm_stats", {}).get("reporter", {})
    if not isinstance(reporter_stats, dict):
        reporter_stats = {}
    repair_retries = int(reporter_stats.get("citation_repair_retries", 0) or 0)
    claim_provenance = reporter_stats.get("claim_provenance", [])
    if isinstance(claim_provenance, list) and claim_provenance:
        claim_count = len(claim_provenance)
        uncited_claims = sum(1 for item in claim_provenance if not item.get("has_citation"))
    else:
        claim_count = int(reporter_stats.get("claim_count", 0) or 0)
        uncited_claims = int(reporter_stats.get("uncited_claims", 0) or 0)
    return {
        "citation_resolution_rate": state.evaluation.citation_resolution_rate,
        "citation_repair_retry_rate": 1.0 if repair_retries else 0.0,
        "citation_repair_retries": repair_retries,
        "uncited_claim_rate": round(uncited_claims / claim_count, 4) if claim_count else 0.0,
        "uncited_claims": uncited_claims,
        "report_claim_count": claim_count,
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


def _load_state_path_map(path: Path) -> dict[str, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("--state-path-map must be a JSON object keyed by question id.")
    return {str(key): str(value) for key, value in payload.items()}


def _quarantined_ids(payload: dict[str, Any]) -> set[str]:
    meta = payload.get("meta", {})
    quarantined = {str(item) for item in meta.get("quarantined_question_ids", [])}
    for item in meta.get("quarantine", []):
        if isinstance(item, dict) and item.get("id"):
            quarantined.add(str(item["id"]))
        elif isinstance(item, str):
            quarantined.add(item)
    for question in payload.get("questions", []):
        if question.get("freeze_status") == "quarantine":
            quarantined.add(str(question["id"]))
    return quarantined


def _effective_questions(payload: dict[str, Any]) -> list[dict[str, Any]]:
    quarantined = _quarantined_ids(payload)
    return [
        question
        for question in payload.get("questions", [])
        if str(question.get("id")) not in quarantined
    ]


def _validate_saved_states(
    questions: list[dict[str, Any]],
    state_path_map: dict[str, str],
) -> None:
    required = [str(item["id"]) for item in questions]
    missing_keys = [qid for qid in required if qid not in state_path_map]
    if missing_keys:
        raise ValueError(f"saved-state map missing effective questions: {missing_keys}")
    for qid in required:
        path = Path(state_path_map[qid])
        if not path.is_file():
            raise FileNotFoundError(f"{qid} saved state unavailable: {path}")
        try:
            ResearchState.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ValueError(f"{qid} saved state is invalid: {path}: {exc}") from exc


def _ledger_cost_cny(path: Path) -> float:
    if not path.exists():
        return 0.0
    total = 0.0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            total += float(json.loads(line).get("cost_cny", 0.0))
        except json.JSONDecodeError:
            continue
    return total


def _ledger_cost_for_prefix(path: Path, run_id_prefix: str) -> float:
    if not path.exists():
        return 0.0
    total = 0.0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(row.get("run_id", "")).startswith(run_id_prefix):
            total += float(row.get("cost_cny", 0.0))
    return total


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
    parser.add_argument("--question-ids", default="")
    parser.add_argument("--state-path-map", default="")
    parser.add_argument("--generation", default="")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--judge-samples", type=int, default=3)
    parser.add_argument("--run-budget-cny", type=float, default=3.0)
    parser.add_argument("--judge-budget-cny", type=float, default=3.0)
    parser.add_argument("--combined-budget-cny", type=float, default=0.0)
    parser.add_argument("--case-cost-reserve-cny", type=float, default=0.12)
    return parser.parse_args()


if __name__ == "__main__":
    main()
