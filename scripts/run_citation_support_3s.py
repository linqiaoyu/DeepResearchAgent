"""Run the release citation verifier three times per saved G3 state.

The Golden states and judge-round results are deliberately read only.  This
script writes a separate verifier result and can resume from that file without
repeating completed paid calls.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from deepresearch_agent.evaluation import JudgeClient, extract_report_claims
from deepresearch_agent.llm import LLMClient
from deepresearch_agent.schemas import ResearchState


Status = Literal["supported", "partially_supported", "unsupported"]
STATUS_VALUES: dict[Status, float] = {
    "supported": 1.0,
    "partially_supported": 0.5,
    "unsupported": 0.0,
}
FREEZE_PATH = Path("data/golden_set/v1/freeze.md")


def main() -> None:
    args = _parse_args()
    _load_env(Path(args.env_path))
    questions = _questions(Path(args.questions))
    if args.question_ids:
        requested = [item.strip() for item in args.question_ids.split(",") if item.strip()]
        available = {str(item["id"]) for item in questions}
        unknown = sorted(set(requested) - available)
        if unknown:
            raise ValueError(f"--question-ids contains unavailable questions: {unknown}")
        questions = [item for item in questions if str(item["id"]) in set(requested)]
    state_paths = _read_json(Path(args.state_path_map))
    baseline = _read_json(Path(args.baseline))
    output_path = Path(args.output)
    existing = _read_json(output_path) if output_path.exists() else {}
    existing_results = {item["id"]: item for item in existing.get("results", [])}

    os.environ.update(
        {
            "DEEPRESEARCH_MODE": "llm",
            "DEEPRESEARCH_LLM_LEDGER_PATH": args.ledger_path,
            "DEEPRESEARCH_LLM_BUDGET_CNY": str(args.budget_cny),
        }
    )
    ledger_path = Path(args.ledger_path)
    judge_client = JudgeClient(
        LLMClient(ledger_path=ledger_path, budget_cny=args.per_call_budget_cny)
    )
    results: list[dict[str, Any]] = []
    for question in questions:
        qid = str(question["id"])
        if qid in existing_results:
            results.append(existing_results[qid])
            print(f"{qid}: resumed", flush=True)
            continue
        _assert_budget(ledger_path, args.budget_cny, args.per_call_reserve_cny)
        state_path = Path(state_paths[qid])
        if not state_path.exists():
            raise FileNotFoundError(f"Saved G3 state is unavailable: {state_path}")
        state = ResearchState.model_validate_json(state_path.read_text(encoding="utf-8"))
        claims = extract_report_claims(state.final_report or "")
        evidence = [_slim_evidence(item.model_dump(mode="json")) for item in state.evidence_store]
        samples = []
        for sample_index in range(1, 4):
            _assert_budget(ledger_path, args.budget_cny, args.per_call_reserve_cny)
            verdict = judge_client.citation_support(
                run_id=f"g3-citation-support-v11-3s-{qid}-{sample_index}",
                claims=claims,
                evidence=evidence,
            )
            samples.append([item.model_dump(mode="json") for item in verdict.verdicts])
        result = _aggregate_case(qid, claims, samples)
        results.append(result)
        _write_output(output_path, questions, baseline, results, ledger_path, args)
        print(f"{qid}: {result['support_rate']:.3f}", flush=True)
    _write_output(output_path, questions, baseline, results, ledger_path, args)


def _aggregate_case(
    qid: str,
    claims: list[dict[str, Any]],
    samples: list[list[dict[str, Any]]],
) -> dict[str, Any]:
    if len(samples) != 3:
        raise ValueError("Three citation-support samples are required.")
    if any(len(sample) != len(claims) for sample in samples):
        counts = [len(sample) for sample in samples]
        raise ValueError(f"{qid}: verdict count does not match claim count: {counts} vs {len(claims)}")
    aligned_samples = [_align_sample(qid, claims, sample) for sample in samples]
    majority_claims = []
    for index, claim in enumerate(claims):
        votes = [sample[index] for sample in aligned_samples]
        status = majority_status([str(vote["status"]) for vote in votes])
        majority_claims.append(
            {
                "claim": claim["claim"],
                "claim_evidence_ids": claim["evidence_ids"],
                "status": status,
                "votes": votes,
            }
        )
    support_rate = round(
        sum(STATUS_VALUES[item["status"]] for item in majority_claims) / len(majority_claims), 3
    ) if majority_claims else 0.0
    sample_rates = [
        round(sum(STATUS_VALUES[str(item["status"])] for item in sample) / len(sample), 3)
        if sample
        else 0.0
        for sample in samples
    ]
    return {
        "id": qid,
        "claim_count": len(claims),
        "support_rate": support_rate,
        "sample_support_rates": sample_rates,
        "claims": majority_claims,
    }


def _align_sample(
    qid: str, claims: list[dict[str, Any]], sample: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    by_claim: dict[str, dict[str, Any]] = {}
    for verdict in sample:
        key = _normalize_claim(str(verdict["claim"]))
        if key in by_claim:
            raise ValueError(f"{qid}: verifier returned duplicate claim text")
        by_claim[key] = verdict
    aligned = []
    for claim in claims:
        verdict = by_claim.get(_normalize_claim(str(claim["claim"])))
        if verdict is None:
            raise ValueError(f"{qid}: verifier returned an unknown claim")
        aligned.append(verdict)
    return aligned


def _normalize_claim(value: str) -> str:
    return re.sub(r"[\s\W_]+", "", value, flags=re.UNICODE)


def majority_status(statuses: list[str]) -> Status:
    if len(statuses) != 3 or any(status not in STATUS_VALUES for status in statuses):
        raise ValueError(f"Expected three valid citation statuses, got {statuses}")
    status, count = Counter(statuses).most_common(1)[0]
    if count >= 2:
        return status  # type: ignore[return-value]
    return sorted(statuses, key=lambda item: STATUS_VALUES[item])[1]  # type: ignore[return-value]


def _write_output(
    output_path: Path,
    questions: list[dict[str, Any]],
    baseline: dict[str, Any],
    results: list[dict[str, Any]],
    ledger_path: Path,
    args: argparse.Namespace,
) -> None:
    ordered = sorted(results, key=lambda item: item["id"])
    rates = [float(item["support_rate"]) for item in ordered]
    baseline_by_id = {item["id"]: item for item in baseline["results"]}
    deltas = [
        round(item["support_rate"] - baseline_by_id[item["id"]]["citation_support"]["support_rate"], 3)
        for item in ordered
    ]
    payload = {
        "version": "v1.1",
        "generation": "G3",
        "retrieval_corpus_as_of": _retrieval_as_of(),
        "verifier": {
            "model": "qwen3.7-plus",
            "samples_per_question": 3,
            "aggregation": "per-claim majority vote; three-way ties use ordinal median (supported=1, partially_supported=0.5, unsupported=0)",
        },
        "effective_question_ids": [str(item["id"]) for item in questions],
        "results": ordered,
        "summary": {
            "cases": len(ordered),
            "avg_citation_support_rate": round(sum(rates) / len(rates), 4) if rates else 0.0,
            "single_sample_avg_citation_support_rate": baseline["summary"]["avg_citation_support_rate"],
            "difference_vs_single_sample": round(
                (sum(rates) / len(rates)) - baseline["summary"]["avg_citation_support_rate"], 4
            ) if rates else 0.0,
            "per_question_differences": {
                item["id"]: delta for item, delta in zip(ordered, deltas, strict=True)
            },
        },
        "cost": {
            "ledger_path": str(ledger_path),
            "calls": _ledger_calls(ledger_path),
            "cost_cny": round(_ledger_cost(ledger_path), 8),
            "budget_cny": args.budget_cny,
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _assert_budget(ledger_path: Path, budget_cny: float, reserve_cny: float) -> None:
    spent = _ledger_cost(ledger_path)
    if spent + reserve_cny > budget_cny:
        raise RuntimeError(
            f"citation-support budget reserve would be exceeded: spent={spent:.6f}, "
            f"reserve={reserve_cny:.6f}, budget={budget_cny:.6f}"
        )


def _ledger_cost(path: Path) -> float:
    if not path.exists():
        return 0.0
    return sum(float(json.loads(line).get("cost_cny", 0.0)) for line in path.read_text(encoding="utf-8").splitlines() if line)


def _ledger_calls(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line)


def _questions(path: Path) -> list[dict[str, Any]]:
    return _read_json(path)["questions"]


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _retrieval_as_of() -> str:
    match = re.search(
        r"^retrieval_corpus_as_of:\s*(\d{4}-\d{2}-\d{2})$",
        FREEZE_PATH.read_text(encoding="utf-8"),
        flags=re.MULTILINE,
    )
    if not match:
        raise ValueError("freeze.md must declare retrieval_corpus_as_of")
    return match.group(1)


def _slim_evidence(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "claim": item.get("claim"),
        "extract_text": item.get("extract_text"),
        "source_id": item.get("source_id"),
    }


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--questions", default="data/golden_set/v1/questions.json")
    parser.add_argument("--question-ids", default="")
    parser.add_argument("--state-path-map", default="_collab/008a_gold-v11/g3_state_path_map.json")
    parser.add_argument("--baseline", default="data/golden_set/v1/results/g3_judge_v11.json")
    parser.add_argument("--output", default="data/golden_set/v1/results/g3_citation_support_3s.json")
    parser.add_argument("--ledger-path", default="_collab/008b_release/citation_support_3s_ledger.jsonl")
    parser.add_argument("--env-path", default=".env")
    parser.add_argument("--budget-cny", type=float, default=2.0)
    parser.add_argument("--per-call-budget-cny", type=float, default=0.06)
    parser.add_argument("--per-call-reserve-cny", type=float, default=0.06)
    return parser.parse_args()


if __name__ == "__main__":
    main()
