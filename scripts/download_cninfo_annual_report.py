"""Download one CNINFO annual-report original through the production adapter."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import httpx

from deepresearch_agent.tools.disclosure_source import CninfoDisclosureSource
from deepresearch_agent.tools.reliable_execution import RunToolContext


class RecordingClient:
    """Keep the exact PDF bytes while delegating production HTTP calls."""

    def __init__(self) -> None:
        self.client = httpx.Client(headers={
            "User-Agent": "Mozilla/5.0 (compatible; DeepResearchHarness/0.1)",
            "Referer": "https://www.cninfo.com.cn/",
            "X-Requested-With": "XMLHttpRequest",
        })
        self.pdf_response: httpx.Response | None = None

    def get(self, url: str, **kwargs: object) -> httpx.Response:
        response = self.client.get(url, **kwargs)
        if url.startswith("https://static.cninfo.com.cn/"):
            self.pdf_response = response
        return response

    def post(self, url: str, **kwargs: object) -> httpx.Response:
        return self.client.post(url, **kwargs)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--security-code", default="600519")
    parser.add_argument("--start-date", default="2026-01-01")
    parser.add_argument("--end-date", default="2026-07-26")
    parser.add_argument("--output-dir", type=Path, default=Path("tests/fixtures"))
    args = parser.parse_args()
    client = RecordingClient()
    context = RunToolContext.for_run(max_retries=0, max_external_search_requests=1, max_external_fetch_requests=2)
    source = CninfoDisclosureSource(client=client, context=context, max_results=1).search(
        args.security_code, "年度报告", date.fromisoformat(args.start_date), date.fromisoformat(args.end_date)
    )[0]
    if client.pdf_response is None:
        raise RuntimeError("production disclosure adapter returned no PDF response")
    output = args.output_dir / f"cninfo_{args.security_code}_{source.published_at}_annual_report.pdf"
    output.write_bytes(client.pdf_response.content)
    print({"output": str(output), "title": source.title, "url": source.url, "published_at": str(source.published_at), "egress": context.external_request_budget.snapshot()})


if __name__ == "__main__":
    main()
