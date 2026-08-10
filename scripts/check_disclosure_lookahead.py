"""Refuse a pipeline that can see a filing before it was published.

R085 established that a financial document has two dates: the end of the period
it reports on, and the day it was disclosed. Point-in-time research must filter
on the second. R112 found that no ingest path had ever written the second one:
`document_version.filing_date` was read but never set, the shipped corpus
declared the *download* date as the publication date, and every layer fell back
to the period end when the disclosure date was missing. On the shipped corpus
the median gap between the two is 109 days, so the fallback made roughly a
quarter of a year of not-yet-public filings visible to an as-of query.

The fix is only worth as much as the thing that stops it regressing, and R085's
result regressed precisely because nothing checked it. This asserts the property
directly rather than any of its ingredients:

1. Every document in the current corpus is dated by a registry, not by
   substitution, and was disclosed after the period it reports on.
2. A document disclosed *after* an as-of date is invisible to a query at that
   date, all the way through storage and retrieval -- while the same document is
   visible once the as-of date passes its disclosure.

Assertion 2 fails if any layer reintroduces the period-end fallback, which is
what `--self-test` demonstrates by re-enabling it.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from deepresearch_agent.rag.backends import StorageLexicalBackend  # noqa: E402
from deepresearch_agent.rag.ingest import SUBSTITUTED_DISCLOSURE_SOURCES  # noqa: E402
from deepresearch_agent.rag.search import RetrievalFilter  # noqa: E402
from deepresearch_agent.storage.protocol import StoredChunk  # noqa: E402
from deepresearch_agent.storage.sqlite_store import SQLiteStore  # noqa: E402

#: The manifest the project ships as current. Earlier versions are immutable
#: history and are deliberately not held to a rule written after them.
CURRENT_CORPUS = ROOT / "data/corpus/finance_v3.json"

_PERIOD_END = "2025-12-31"
_DISCLOSED_ON = "2026-04-15"
_BEFORE_DISCLOSURE = "2026-02-01"
_AFTER_DISCLOSURE = "2026-05-01"


def check_corpus(path: Path) -> list[str]:
    """Every document must carry a disclosure date something established."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    documents = payload["documents"]
    failures: list[str] = []
    substituted = [
        entry
        for entry in documents
        if not entry.get("published_at")
        or entry.get("published_at_source", "") in SUBSTITUTED_DISCLOSURE_SOURCES
    ]
    if substituted:
        failures.append(
            f"{len(substituted)} of {len(documents)} documents have a substituted "
            f"disclosure date, e.g. {substituted[0]['path']}"
        )
    backwards = [
        entry
        for entry in documents
        if entry.get("published_at") and str(entry["published_at"]) < str(entry["effective_date"])
    ]
    if backwards:
        failures.append(
            f"{len(backwards)} document(s) claim to be disclosed before their period "
            f"ended, e.g. {backwards[0]['path']}"
        )
    if not failures:
        lags = [
            (
                date.fromisoformat(str(entry["published_at"]))
                - date.fromisoformat(str(entry["effective_date"]))
            ).days
            for entry in documents
        ]
        lags.sort()
        print(
            f"corpus_documents={len(documents)} substituted_disclosure=0 "
            f"median_disclosure_lag_days={lags[len(lags) // 2]}"
        )
    return failures


def check_lookahead(*, honour_disclosure_date: bool = True) -> list[str]:
    """A filing must be invisible until the as-of date reaches its disclosure."""

    with tempfile.TemporaryDirectory() as directory:
        store = SQLiteStore(Path(directory) / "lookahead.db")
        store.record_document_version(
            canonical_url="https://example.test/lookahead/annual-report",
            file_sha256="d" * 64,
            effective_date=_PERIOD_END,
            published_at=_DISCLOSED_ON,
            chunks=[
                StoredChunk(
                    id="lookahead-chunk",
                    char_start=0,
                    char_end=40,
                    page_number=1,
                    effective_date=_PERIOD_END,
                    published_at=_DISCLOSED_ON,
                    content="annual revenue disclosure statement text",
                    entity_id="lookaheadco",
                )
            ],
        )
        backend = StorageLexicalBackend(store=store)

        def hits(as_of: str) -> list[str]:
            chunks = backend.search(
                query="annual revenue disclosure",
                filters=RetrievalFilter(as_of=date.fromisoformat(as_of)),
                limit=10,
            )
            if not honour_disclosure_date:
                # The pre-R112 behaviour: treat the period end as the date the
                # document became visible whenever a disclosure date is absent
                # or ignored. Reinstating it must make this check fail.
                chunks = backend.search(
                    query="annual revenue disclosure",
                    filters=RetrievalFilter(as_of=date.fromisoformat("9999-12-31")),
                    limit=10,
                )
                chunks = [
                    chunk for chunk in chunks if chunk.effective_date.isoformat() <= as_of
                ]
            return [chunk.chunk_id for chunk in chunks]

        failures: list[str] = []
        early = hits(_BEFORE_DISCLOSURE)
        if early:
            failures.append(
                f"a filing disclosed {_DISCLOSED_ON} was visible as of "
                f"{_BEFORE_DISCLOSURE}: {early}"
            )
        late = hits(_AFTER_DISCLOSURE)
        if not late:
            failures.append(
                f"a filing disclosed {_DISCLOSED_ON} was still invisible as of "
                f"{_AFTER_DISCLOSURE}"
            )
        if not failures:
            print(
                f"lookahead_probe=PASS invisible_before={_BEFORE_DISCLOSURE} "
                f"visible_after={_AFTER_DISCLOSURE}"
            )
        return failures


def check_undated_is_withheld() -> list[str]:
    """A document with no disclosure date must be withheld, not back-dated.

    R112 removed the fallback at read time; R113 found the same substitution
    still happening at write time, where `record_document_version` stored the
    period end as though it were a disclosure date whenever none was declared.
    That is not a smaller bug -- it materialises the lookahead in the database,
    where it looks like data rather than a default.

    An unknown date must therefore make a chunk invisible at every as-of. The
    empty string sorts before every real date, so the failure mode this guards
    is specifically that undated chunks become the ones that are *always*
    visible.
    """

    with tempfile.TemporaryDirectory() as directory:
        store = SQLiteStore(Path(directory) / "undated.db")
        store.record_document_version(
            canonical_url="https://example.test/undated/report",
            file_sha256="e" * 64,
            effective_date=_PERIOD_END,
            chunks=[
                StoredChunk(
                    id="undated-chunk",
                    char_start=0,
                    char_end=40,
                    page_number=1,
                    effective_date=_PERIOD_END,
                    content="annual revenue disclosure statement text",
                    entity_id="undatedco",
                )
            ],
        )
        failures: list[str] = []
        for as_of in (_BEFORE_DISCLOSURE, _AFTER_DISCLOSURE, "9999-12-31"):
            visible = [chunk.id for chunk in store.list_ready_chunks(as_of=as_of)]
            if visible:
                failures.append(
                    f"a document with no disclosure date was visible as of {as_of}: {visible}"
                )
            resolved = store.resolve_ready_chunks(["undated-chunk"], as_of=as_of)
            if resolved:
                failures.append(
                    f"resolve_ready_chunks returned an undated chunk as of {as_of}"
                )
        if not failures:
            print("undated_withheld=PASS invisible_at_every_as_of=true")
        return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test and not check_lookahead(honour_disclosure_date=False):
        print(
            "disclosure_lookahead=FAIL self-test did not detect the period-end fallback",
            file=sys.stderr,
        )
        return 1

    failures = check_corpus(CURRENT_CORPUS) + check_lookahead() + check_undated_is_withheld()
    if failures:
        for failure in failures:
            print(f"disclosure_lookahead=FAIL {failure}", file=sys.stderr)
        return 1
    print("disclosure_lookahead=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
