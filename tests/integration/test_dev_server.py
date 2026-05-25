from __future__ import annotations

import importlib
import json
import os
import socket
import sys
import tempfile
import threading
import unittest
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

from deepresearch_agent.settings import Settings
from deepresearch_agent.workflow import DeepResearchEngine


class DevServerTests(unittest.TestCase):
    def test_get_research_returns_checkpointed_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage_path = Path(tmp) / "research.db"
            dev_server = _import_dev_server_with_storage(storage_path)

            engine = DeepResearchEngine(settings=Settings(storage_path=storage_path, max_critic_iter=1))
            state = engine.run(topic="fallback checkpoint contract", depth_level=1)

            self.assertEqual(
                dev_server.research_state_path_id(f"/research/{state.research_id}"),
                state.research_id,
            )
            self.assertIsNone(dev_server.research_state_path_id(f"/research/{state.research_id}/report"))

            payload, status = dev_server.research_state_response(engine, state.research_id)

            self.assertEqual(status, HTTPStatus.OK)
            self.assertEqual(payload["research_id"], state.research_id)
            self.assertEqual(payload["topic"], "fallback checkpoint contract")
            self.assertIn("current_phase", payload)
            self.assertIn("status", payload)

            missing_payload, missing_status = dev_server.research_state_response(engine, "does-not-exist")
            self.assertEqual(missing_status, HTTPStatus.NOT_FOUND)
            self.assertEqual(missing_payload, {"error": "research_id not found"})
            json.dumps(payload)

    def test_fallback_api_routes_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage_path = Path(tmp) / "research.db"
            dev_server = _import_dev_server_with_storage(storage_path)
            original_engine = dev_server.DeepResearchHandler.engine
            dev_server.DeepResearchHandler.engine = DeepResearchEngine(
                settings=Settings(storage_path=storage_path, max_critic_iter=1)
            )
            client = _FallbackServerClient(dev_server.DeepResearchHandler)
            try:
                post_payload = {"topic": "fallback api route smoke", "depth_level": 1}
                post_status, post_response = client.request_json("POST", "/research", post_payload)
                self.assertEqual(post_status, HTTPStatus.OK)

                for key in ("research_id", "status", "current_phase", "report_url"):
                    self.assertIn(key, post_response)
                research_id = post_response["research_id"]

                state_status, state_response = client.request_json("GET", f"/research/{research_id}")
                self.assertEqual(state_status, HTTPStatus.OK)
                self.assertEqual(state_response["research_id"], research_id)
                self.assertEqual(state_response["topic"], "fallback api route smoke")

                report_status, report_response = client.request_json("GET", f"/research/{research_id}/report")
                self.assertEqual(report_status, HTTPStatus.OK)
                self.assertEqual(report_response["research_id"], research_id)
                self.assertIsInstance(report_response["report"], str)
                self.assertTrue(report_response["report"])

                metrics_status, metrics_response = client.request_json("GET", "/metrics")
                self.assertEqual(metrics_status, HTTPStatus.OK)
                self.assertIsInstance(metrics_response, list)

                missing_status, missing_payload = client.request_json("GET", "/research/does-not-exist")
                self.assertEqual(missing_status, HTTPStatus.NOT_FOUND)
                self.assertEqual(missing_payload, {"error": "research_id not found"})
            finally:
                client.close()
                dev_server.DeepResearchHandler.engine = original_engine


def _import_dev_server_with_storage(storage_path: Path):
    original_storage_path = os.environ.get("DEEPRESEARCH_STORAGE_PATH")
    os.environ["DEEPRESEARCH_STORAGE_PATH"] = str(storage_path)
    try:
        if "scripts.dev_server" in sys.modules:
            return importlib.reload(sys.modules["scripts.dev_server"])
        return importlib.import_module("scripts.dev_server")
    finally:
        if original_storage_path is None:
            os.environ.pop("DEEPRESEARCH_STORAGE_PATH", None)
        else:
            os.environ["DEEPRESEARCH_STORAGE_PATH"] = original_storage_path


class _FallbackServerClient:
    def __init__(self, handler_class: type) -> None:
        try:
            self._transport = _LoopbackServerClient(handler_class)
        except PermissionError:
            self._transport = _SocketPairServerClient(handler_class)

    def request_json(self, method: str, path: str, payload: object | None = None) -> tuple[int, object]:
        return self._transport.request_json(method, path, payload)

    def close(self) -> None:
        self._transport.close()


class _LoopbackServerClient:
    def __init__(self, handler_class: type) -> None:
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), handler_class)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        self._base_url = f"http://127.0.0.1:{self._server.server_address[1]}"

    def request_json(self, method: str, path: str, payload: object | None = None) -> tuple[int, object]:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(
            f"{self._base_url}{path}",
            data=data,
            headers={"content-type": "application/json"},
            method=method,
        )
        try:
            with urlopen(request, timeout=10) as response:
                self._assert_json_response(response.headers.get_content_type())
                return response.status, json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            if not hasattr(exc, "code") or not hasattr(exc, "read"):
                raise
            self._assert_json_response(exc.headers.get_content_type())
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def close(self) -> None:
        self._server.shutdown()
        self._thread.join(timeout=5)
        self._server.server_close()
        if self._thread.is_alive():
            raise AssertionError("fallback HTTP server thread did not stop")

    def _assert_json_response(self, content_type: str) -> None:
        if content_type != "application/json":
            raise AssertionError(f"expected application/json response, got {content_type!r}")


class _SocketPairServerClient:
    def __init__(self, handler_class: type) -> None:
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), handler_class, bind_and_activate=False)

    def request_json(self, method: str, path: str, payload: object | None = None) -> tuple[int, object]:
        body = json.dumps(payload).encode("utf-8") if payload is not None else b""
        request = (
            f"{method} {path} HTTP/1.1\r\n"
            "Host: 127.0.0.1\r\n"
            "Connection: close\r\n"
            "Accept: application/json\r\n"
            "Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n"
            "\r\n"
        ).encode("utf-8") + body
        server_socket, client_socket = socket.socketpair()
        try:
            self._server.process_request(server_socket, ("127.0.0.1", 0))
            client_socket.sendall(request)
            client_socket.shutdown(socket.SHUT_WR)
            response = self._read_response(client_socket)
        finally:
            client_socket.close()
        return self._parse_json_response(response)

    def close(self) -> None:
        self._server.server_close()

    def _read_response(self, client_socket: socket.socket) -> bytes:
        chunks = []
        while True:
            chunk = client_socket.recv(65536)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)

    def _parse_json_response(self, response: bytes) -> tuple[int, object]:
        header_bytes, body = response.split(b"\r\n\r\n", 1)
        headers = header_bytes.decode("iso-8859-1").split("\r\n")
        status = int(headers[0].split()[1])
        content_type = ""
        for header in headers[1:]:
            name, _, value = header.partition(":")
            if name.lower() == "content-type":
                content_type = value.strip().split(";", maxsplit=1)[0]
                break
        if content_type != "application/json":
            raise AssertionError(f"expected application/json response, got {content_type!r}")
        return status, json.loads(body.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
