"""Acceptance probe for task 081 block D fetch and owner-token boundaries."""

from __future__ import annotations

from typing import Any

from deepresearch_agent.security import FetchPolicy
from deepresearch_agent.tools.tavily_search import TavilySearchProvider


class Response:
    def __init__(self, *, status: int = 200, headers: dict[str, str] | None = None, chunks: list[bytes] | None = None) -> None:
        self.status_code = status
        self.headers = headers or {"content-type": "text/html"}
        self._chunks = chunks or [b"<html><title>x</title>body</html>"]
        self.read = 0

    @property
    def content(self) -> bytes:
        raise AssertionError("response.content must not be materialized")

    def iter_bytes(self):
        for chunk in self._chunks:
            self.read += len(chunk)
            yield chunk

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError("status")


class Client:
    def __init__(self, responses: list[Response]) -> None:
        self.responses = responses
        self.calls = 0

    def get(self, _url: str, **_kwargs: Any) -> Response:
        self.calls += 1
        return self.responses.pop(0)


def provider(client: Client, policy: FetchPolicy | None = None) -> TavilySearchProvider:
    return TavilySearchProvider("test-key", client=client, max_retries=0, fetch_policy=policy)


def main() -> int:
    blocked = ["http://127.0.0.1/", "http://169.254.169.254/", "http://[::1]/", "http://10.0.0.1/", "file:///etc/passwd"]
    client = Client([])
    refused = sum(provider(client).fetch(url) is None for url in blocked)
    print(f"refused={refused} client_calls={client.calls}")

    redirected = provider(Client([Response(status=302, headers={"location": "http://127.0.0.1/"})])).fetch("https://example.test")
    print(f"redirect_refused={redirected is None}")

    body = Response(chunks=[b"x"] * 100)
    max_bytes = 25
    provider(Client([body]), FetchPolicy(max_response_bytes=max_bytes)).fetch("https://example.test")
    print(f"bytes_read={body.read} max_response_bytes={max_bytes}")

    wrong_type = provider(Client([Response(headers={"content-type": "image/png"})])).fetch("https://example.test")
    print(f"content_type_refused={wrong_type is None}")

    redirects = [Response(status=302, headers={"location": "https://example.test/next"}) for _ in range(2)]
    limited = provider(Client(redirects), FetchPolicy(max_redirects=1)).fetch("https://example.test")
    print(f"redirect_limit_enforced={limited is None}")
    return int(not (refused == 5 and client.calls == 0 and redirected is None and body.read <= max_bytes and wrong_type is None and limited is None))


if __name__ == "__main__":
    raise SystemExit(main())
