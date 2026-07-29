"""Download only the public originals listed in a frozen finance corpus manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_RETRIES = 2
DEFAULT_REQUEST_BUDGET = 120
USER_AGENT = "DeepResearchAgent-finance-v1/1.0 public-corpus-fetcher"
BLOCKED_MARKERS = (b"captcha", b"access denied", b"verify you are human", b"unusual traffic")


def _is_original_response(*, path: Path, data: bytes, content_type: str) -> str | None:
    if not data:
        return "zero_byte_response"
    lowered = data[:200_000].lower()
    if any(marker in lowered for marker in BLOCKED_MARKERS):
        return "blocked_or_captcha_response"
    if path.suffix.lower() == ".pdf":
        if not data.startswith(b"%PDF-"):
            return "html_or_non_pdf_disguised_as_pdf"
    elif path.suffix.lower() in {".html", ".htm"}:
        if b"<html" not in lowered and "html" not in content_type.lower():
            return "unexpected_non_html_response"
    return None


def _download(url: str, *, timeout: int, retries: int, budget: list[int]) -> tuple[bytes | None, str | None]:
    for attempt in range(retries + 1):
        if budget[0] <= 0:
            return None, "request_budget_exhausted"
        budget[0] -= 1
        try:
            request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/pdf,text/html"})
            with urlopen(request, timeout=timeout) as response:
                if response.status != 200:
                    return None, f"http_status_{response.status}"
                data = response.read()
                content_length = response.headers.get("Content-Length")
                if content_length and len(data) != int(content_length):
                    return None, "truncated_response"
                issue = _is_original_response(path=Path(url), data=data, content_type=response.headers.get_content_type())
                if issue:
                    return None, issue
                return data, None
        except HTTPError as error:
            if error.code < 500 or attempt == retries:
                return None, f"http_status_{error.code}"
        except (URLError, TimeoutError, ValueError) as error:
            if attempt == retries:
                return None, f"network_error_{type(error).__name__}"
        time.sleep(min(2**attempt, 4))
    return None, "unreachable"


def download_manifest(*, input_dir: Path, corpus_path: Path, timeout: int, retries: int, request_budget: int) -> int:
    payload = json.loads(corpus_path.read_text(encoding="utf-8"))
    documents = payload.get("documents")
    if payload.get("schema_version") != 1 or not isinstance(documents, list):
        raise ValueError("expected corpus schema_version=1 and a documents list")
    budget = [request_budget]
    downloaded = skipped = failures = 0
    for entry in documents:
        relative = Path(entry["path"])
        target = (input_dir / relative).resolve()
        if input_dir.resolve() not in target.parents:
            raise ValueError(f"unsafe manifest path: {entry['path']}")
        expected_hash = entry["sha256"]
        expected_bytes = entry["bytes"]
        if target.is_file():
            current = target.read_bytes()
            if len(current) == expected_bytes and hashlib.sha256(current).hexdigest() == expected_hash:
                skipped += 1
                continue
        data, issue = _download(entry["url"], timeout=timeout, retries=retries, budget=budget)
        if issue or data is None:
            failures += 1
            print(f"failed path={entry['path']} reason={issue}")
            continue
        actual_hash = hashlib.sha256(data).hexdigest()
        if len(data) != expected_bytes or actual_hash != expected_hash:
            failures += 1
            print(f"failed path={entry['path']} reason=manifest_integrity_mismatch")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        downloaded += 1
        time.sleep(0.12)
    print(f"downloaded={downloaded} skipped={skipped} failures={failures} requests_used={request_budget - budget[0]}")
    return 1 if failures else 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("data/raw/finance_v1"))
    parser.add_argument("--corpus", type=Path, default=Path("data/corpus/finance_v1.json"))
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--retries", type=int, default=DEFAULT_RETRIES)
    parser.add_argument("--request-budget", type=int, default=DEFAULT_REQUEST_BUDGET)
    args = parser.parse_args()
    raise SystemExit(download_manifest(input_dir=args.input, corpus_path=args.corpus, timeout=args.timeout, retries=args.retries, request_budget=args.request_budget))


if __name__ == "__main__":
    main()
