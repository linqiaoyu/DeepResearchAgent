"""Read-only self-rank diagnostic for frozen retrieval labels."""

from __future__ import annotations
import hashlib
import json
import sqlite3
import time
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5
import certifi
import httpx
from dotenv import dotenv_values

from deepresearch_agent.llm_config import DASHSCOPE_EMBEDDING_MODEL
from deepresearch_agent.rag.chunking import CHUNKER_VERSION

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    env = dotenv_values(ROOT / ".env")
    base = str(env["DEEPRESEARCH_QDRANT_URL"]).rstrip("/")
    col = str(env["DEEPRESEARCH_QDRANT_COLLECTION"])
    headers = {"api-key": str(env.get("DEEPRESEARCH_QDRANT_API_KEY") or "")}
    questions = json.loads((ROOT / "data/golden_set/retrieval_v1/questions.json").read_text())
    chosen = []
    for kind in ("table", "cross_period"):
        chosen += [q for q in questions if q["question_type"] == kind and q["labels"]]
    chosen += [
        q
        for q in questions
        if q["question_type"] not in {"table", "cross_period", "refusal"} and q["labels"]
    ]
    db = sqlite3.connect(ROOT / "data/runtime/047-assets.db")
    rows = []
    with httpx.Client(headers=headers, timeout=30.0, verify=certifi.where()) as client:
        warmed = time.perf_counter()
        info = client.get(f"{base}/collections/{col}", timeout=60.0)
        info.raise_for_status()
        print(
            json.dumps(
                {
                    "warmup_status": info.status_code,
                    "warmup_s": round(time.perf_counter() - warmed, 3),
                }
            )
        )
        for q in chosen[:20]:
            label = q["labels"][0]
            hit = db.execute(
                "select c.id, c.content, c.char_start, c.char_end, v.file_sha256 "
                "from chunk c join document_version v on v.id=c.document_version_id "
                'where c.document_version_id=? and c.char_start<? and c.char_end>? and c.status="ready" '
                "order by c.char_start limit 1",
                (label["document_version_id"], label["char_end"], label["char_start"]),
            ).fetchone()
            if not hit:
                raise ValueError(q["id"])
            target, content, start, end, document_sha256 = hit
            expected = str(
                uuid5(
                    NAMESPACE_URL,
                    f"{document_sha256}:{start}:{end}:{hashlib.sha256(content.encode('utf-8')).hexdigest()}",
                )
            )
            if target != expected:
                raise RuntimeError(f"chunk_id_formula_mismatch question_id={q['id']}")
            point_id = str(
                uuid5(NAMESPACE_URL, f"{target}:{DASHSCOPE_EMBEDDING_MODEL}:{CHUNKER_VERSION}")
            )
            # ``chunk_id`` has no online payload index.  Point identity is deterministic,
            # so has_id fetches exactly one point without creating an index or writing.
            scroll = client.post(
                f"{base}/collections/{col}/points/scroll",
                json={
                    "filter": {"must": [{"has_id": [point_id]}]},
                    "limit": 1,
                    "with_vector": True,
                    "with_payload": ["chunk_id"],
                },
            )
            if scroll.status_code != 200:
                raise RuntimeError(
                    f"scroll_http_status={scroll.status_code} body={scroll.text[:400]}"
                )
            found = scroll.json()["result"]["points"]
            if len(found) != 1:
                raise RuntimeError(f"point_not_found question_id={q['id']}")
            point = found[0]
            search = client.post(
                f"{base}/collections/{col}/points/search",
                json={
                    "vector": point["vector"],
                    "limit": 20,
                    "with_payload": ["chunk_id"],
                    "with_vector": False,
                },
            )
            if search.status_code != 200:
                raise RuntimeError(
                    f"search_http_status={search.status_code} body={search.text[:400]}"
                )
            points = search.json()["result"]
            rank = next(
                (
                    i + 1
                    for i, p in enumerate(points)
                    if p.get("payload", {}).get("chunk_id") == target
                ),
                None,
            )
            rows.append(
                {
                    "question_id": q["id"],
                    "type": q["question_type"],
                    "chunk_id": target,
                    "self_rank": rank,
                    "top1_score": points[0]["score"],
                }
            )
    print(
        json.dumps(
            {
                "rows": rows,
                "self_rank_at_1": sum(r["self_rank"] == 1 for r in rows),
                "total": len(rows),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
