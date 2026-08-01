"""Show why raw Chinese BM25 terms cannot match the English 20-F corpus."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def chinese_lexical_terms(text: str) -> list[str]:
    terms: list[str] = []
    for run in re.findall(r"[\u3400-\u9fff]+", text):
        terms.extend(run[index : index + 2] for index in range(max(0, len(run) - 1)))
        if len(run) == 1:
            terms.append(run)
    terms.extend(token.lower() for token in re.findall(r"[A-Za-z0-9_]+", text))
    return terms


def probe(questions_path: Path, output: Path) -> dict[str, object]:
    questions = json.loads(questions_path.read_text(encoding="utf-8"))
    selected = [item for item in questions if item["question_type"] != "refusal"][:20]
    rows = []
    for item in selected:
        question = str(item["question"])
        quoted_english = re.findall(r"[\"“]([^\"”]+)[\"”]", question)
        raw_terms = chinese_lexical_terms(question)
        english_terms = [term.lower() for phrase in quoted_english for term in re.findall(r"[A-Za-z0-9_]+", phrase)]
        rows.append(
            {
                "id": item["id"],
                "question": question,
                "raw_chinese_terms": raw_terms,
                "quoted_english_terms": english_terms,
                "cjk_bigram_count": sum(bool(re.fullmatch(r"[\u3400-\u9fff]{2}", term)) for term in raw_terms),
            }
        )
    if len(rows) != 20:
        raise ValueError(f"expected 20 answerable questions, got {len(rows)}")
    result: dict[str, object] = {
        "schema_version": 1,
        "method": "deterministic CJK-bigram and ASCII-token comparison; no provider calls",
        "questions": rows,
        "summary": {
            "questions": len(rows),
            "queries_with_cjk_bigrams": sum(bool(row["cjk_bigram_count"]) for row in rows),
            "queries_with_quoted_english": sum(bool(row["quoted_english_terms"]) for row in rows),
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(probe(args.questions, args.output)["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
