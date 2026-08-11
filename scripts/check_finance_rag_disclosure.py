"""Prove finance retrieval fidelity and disclosure provenance without a new 30-case run.

R154 deliberately reuses the R149 diagnostic cohort. It reports the one case
that failed before providers as absent rather than converting 29/30 into a
product-quality claim. A local end-to-end RAG probe separately proves that every
delivered candidate carries the index, disclosure-date source and as-of reason
that a later live run must persist.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from deepresearch_agent.rag.backends import StorageLexicalBackend  # noqa: E402
from deepresearch_agent.rag.search import RagSearchService  # noqa: E402
from deepresearch_agent.storage import SQLiteStore, StoredChunk  # noqa: E402

R149_PROOF = ROOT / "docs/decisions/149/live-loss-baseline-proof.json"
CORPUS = ROOT / "data/corpus/finance_v3.json"
REQUIRED_TRACE_FIELDS = {
    "index_version",
    "published_at",
    "published_at_source",
    "as_of_filter_reason",
}


def check_r149_fidelity(payload: dict[str, object]) -> list[str]:
    cases = payload.get("cases")
    if not isinstance(cases, list):
        return ["R149 proof has no cases list"]
    failures: list[str] = []
    ids = [case.get("id") for case in cases if isinstance(case, dict)]
    expected = [f"Q{number:02d}" for number in range(1, 31)]
    if ids != expected:
        failures.append("R149 cases are not the complete ordered frozen 30-case cohort")
    live = []
    absent = []
    for case in cases:
        if not isinstance(case, dict):
            failures.append("R149 contains a non-object case")
            continue
        fidelity = case.get("provider_fidelity")
        retrieval = fidelity.get("retrieval") if isinstance(fidelity, dict) else None
        (live if retrieval == "live" else absent).append(str(case.get("id")))
    if live != [identifier for identifier in expected if identifier != "Q21"]:
        failures.append(f"retrieval live set changed: {live}")
    if absent != ["Q21"]:
        failures.append(f"pre-provider error set changed: {absent}")
    errors = {
        str(case.get("id")): case.get("error_type")
        for case in cases
        if isinstance(case, dict) and case.get("status") == "error"
    }
    if set(errors) != {"Q13", "Q21"}:
        failures.append(f"diagnostic error set changed: {errors}")
    return failures


def check_corpus_provenance(payload: dict[str, object]) -> list[str]:
    documents = payload.get("documents")
    if not isinstance(documents, list) or not documents:
        return ["finance corpus has no documents"]
    missing = [
        str(item.get("path"))
        for item in documents
        if not isinstance(item, dict)
        or not item.get("published_at")
        or not item.get("published_at_source")
    ]
    return [f"finance corpus lacks disclosure provenance: {missing[:3]}"] if missing else []


def candidate_probe(*, erase_provenance: bool = False) -> tuple[list[str], int]:
    with tempfile.TemporaryDirectory() as directory:
        store = SQLiteStore(Path(directory) / "rag.db")
        source = "" if erase_provenance else "exchange_registry"
        chunk = StoredChunk(
            id="finance-disclosure-probe",
            char_start=0,
            char_end=31,
            page_number=1,
            effective_date="2025-12-31",
            published_at="2026-03-20",
            published_at_source=source,
            content="annual revenue disclosure was 42 billion",
            entity_id="issuer",
        )
        store.record_document_version(
            canonical_url="https://example.test/issuer/annual-report",
            file_sha256="a" * 64,
            effective_date="2025-12-31",
            published_at="2026-03-20",
            published_at_source=source,
            chunks=[chunk],
        )
        backend = StorageLexicalBackend(store=store)
        service = RagSearchService(
            lexical=backend,
            dense=backend,
            reranker=None,
            retrieval_top_k=4,
            rerank_top_n=1,
            rerank_enabled=False,
            rerank_fail_open=False,
            index_version="finance-v3",
        )
        before = service.search(query="annual revenue disclosure", as_of="2026-03-19")
        after = service.search(query="annual revenue disclosure", as_of="2026-03-20")

    failures: list[str] = []
    if before["candidates"]:
        failures.append("candidate was visible before disclosure")
    candidates = after["candidates"]
    if not isinstance(candidates, list) or len(candidates) != 1:
        failures.append("candidate was not delivered on its disclosure date")
        return failures, 0
    candidate = candidates[0]
    if not isinstance(candidate, dict):
        return ["delivered candidate is not an object"], 0
    missing = [field for field in REQUIRED_TRACE_FIELDS if not candidate.get(field)]
    if missing:
        failures.append(f"candidate trace lacks {sorted(missing)}")
    if candidate.get("index_version") != "finance-v3":
        failures.append("candidate index version drifted")
    if candidate.get("as_of_filter_reason") != "published_on_or_before_as_of":
        failures.append("candidate as-of reason drifted")
    return failures, 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument(
        "--mutation",
        choices=("missing-provenance", "fabricated-q21-live"),
        help="run one intentional bad implementation and require a real failure",
    )
    args = parser.parse_args()

    r149 = json.loads(R149_PROOF.read_text(encoding="utf-8"))
    if args.mutation == "fabricated-q21-live":
        r149["cases"][20]["provider_fidelity"]["retrieval"] = "live"
    failures = check_r149_fidelity(r149)
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    failures.extend(check_corpus_provenance(corpus))
    probe_failures, candidate_count = candidate_probe(
        erase_provenance=args.mutation == "missing-provenance"
    )
    failures.extend(probe_failures)
    if args.self_test:
        mutated, _ = candidate_probe(erase_provenance=True)
        if not mutated:
            failures.append("self-test accepted a candidate without published_at_source")
        mutated_proof = json.loads(R149_PROOF.read_text(encoding="utf-8"))
        mutated_proof["cases"][20]["provider_fidelity"]["retrieval"] = "live"
        if not check_r149_fidelity(mutated_proof):
            failures.append("self-test accepted a fabricated Q21 live fidelity")
    if failures:
        for failure in failures:
            print(f"finance_rag_disclosure=FAIL {failure}", file=sys.stderr)
        return 1
    print(
        "finance_rag_disclosure=PASS cohort=30 retrieval_live=29 "
        "pre_provider_error=1 successful_live=28 lookahead_violations=0 "
        f"candidate_trace={candidate_count}/{candidate_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
