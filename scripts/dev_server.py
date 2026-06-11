from __future__ import annotations

import argparse
import json
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from deepresearch_agent.schemas import ResearchRequest
from deepresearch_agent.workflow import DeepResearchEngine


def research_state_path_id(path: str) -> str | None:
    path_parts = path.strip("/").split("/")
    if len(path_parts) == 2 and path_parts[0] == "research" and path_parts[1]:
        return path_parts[1]
    return None


def research_state_response(engine: DeepResearchEngine, research_id: str) -> tuple[object, HTTPStatus]:
    state = engine.load_state(research_id)
    if not state:
        return {"error": "research_id not found"}, HTTPStatus.NOT_FOUND
    return state.model_dump(mode="json"), HTTPStatus.OK


class DeepResearchHandler(BaseHTTPRequestHandler):
    engine = DeepResearchEngine()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_html(self._home_html())
            return
        if parsed.path == "/health":
            self._send_json({"status": "ok"})
            return
        if parsed.path == "/metrics":
            self._send_json([item.model_dump(mode="json") for item in self.engine.store.latest_metrics()])
            return
        if parsed.path.startswith("/research/") and parsed.path.endswith("/report"):
            research_id = parsed.path.split("/")[2]
            state = self.engine.load_state(research_id)
            if not state:
                self._send_json({"error": "research_id not found"}, status=HTTPStatus.NOT_FOUND)
                return
            self._send_json({"research_id": research_id, "report": state.final_report or ""})
            return
        research_id = research_state_path_id(parsed.path)
        if research_id:
            payload, status = research_state_response(self.engine, research_id)
            self._send_json(payload, status=status)
            return
        if parsed.path == "/run":
            topic = parse_qs(parsed.query).get("topic", ["AI Agent 在财富管理行业的落地机会研究"])[0]
            state = self.engine.run(topic=topic, depth_level=2)
            self._send_html(self._report_html(state.research_id, state.final_report or ""))
            return
        self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/research":
            self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
            return
        length = int(self.headers.get("content-length", "0"))
        body = self.rfile.read(length).decode("utf-8") if length else "{}"
        request = ResearchRequest.model_validate(json.loads(body))
        state = self.engine.run(topic=request.topic, depth_level=request.depth_level)
        self._send_json(
            {
                "research_id": state.research_id,
                "status": state.status,
                "current_phase": state.current_phase,
                "report_url": f"/research/{state.research_id}/report",
                "metrics": state.evaluation.model_dump(mode="json") if state.evaluation else None,
            }
        )

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send_json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_html(self, html: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = html.encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _home_html(self) -> str:
        return """
<!doctype html>
<html lang="zh">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>DeepResearchAgent</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; background: #f7f8fa; color: #20242a; }
    main { max-width: 960px; margin: 0 auto; padding: 32px 20px; }
    form { display: grid; grid-template-columns: 1fr auto; gap: 12px; margin-bottom: 20px; }
    input { font-size: 16px; padding: 12px; border: 1px solid #cfd5dd; border-radius: 6px; }
    button { font-size: 16px; padding: 12px 18px; border: 0; border-radius: 6px; background: #176b5d; color: white; cursor: pointer; }
    pre { white-space: pre-wrap; background: white; border: 1px solid #d9dee5; border-radius: 6px; padding: 16px; overflow-x: auto; }
  </style>
</head>
<body>
  <main>
    <h1>DeepResearchAgent</h1>
    <form action="/run" method="get">
      <input name="topic" value="AI Agent 在财富管理行业的落地机会研究" />
      <button type="submit">Run</button>
    </form>
    <pre>POST /research
GET /metrics
GET /research/{id}
GET /research/{id}/report</pre>
  </main>
</body>
</html>
"""

    def _report_html(self, research_id: str, report: str) -> str:
        escaped = report.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return f"""
<!doctype html>
<html lang="zh">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>DeepResearchAgent Report</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; background: #f7f8fa; color: #20242a; }}
    main {{ max-width: 1040px; margin: 0 auto; padding: 28px 20px; }}
    a {{ color: #176b5d; }}
    pre {{ white-space: pre-wrap; background: white; border: 1px solid #d9dee5; border-radius: 6px; padding: 18px; line-height: 1.5; }}
  </style>
</head>
<body>
  <main>
    <a href="/">New run</a>
    <h1>{research_id}</h1>
    <pre>{escaped}</pre>
  </main>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), DeepResearchHandler)
    print(f"Serving DeepResearchAgent fallback UI at http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
