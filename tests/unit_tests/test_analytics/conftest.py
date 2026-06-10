from __future__ import annotations

import http.server
import json
import threading
from collections.abc import Iterator
from typing import NamedTuple

import pytest


class CaptureRecord(NamedTuple):
    """A single request received by the capture server.

    Unpacks as ``(path, body, content_type)`` for callers that only care about
    the request tuple, while still exposing named fields.
    """

    path: str
    body: object
    content_type: str | None


class _CaptureHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        try:
            body: object = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            body = None
        self.server.records.append(  # type: ignore[attr-defined]
            CaptureRecord(self.path, body, self.headers.get("Content-Type"))
        )
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, format: str, *args: object) -> None:
        pass  # silence the default request logging


class CaptureServer:
    """A tiny loopback HTTP server that records the requests it receives."""

    def __init__(self) -> None:
        self._httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _CaptureHandler)
        self._httpd.records = []  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    def __enter__(self) -> CaptureServer:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._httpd.shutdown()
        self._thread.join(timeout=5)
        self._httpd.server_close()

    @property
    def url(self) -> str:
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}"

    @property
    def captured(self) -> list[CaptureRecord]:
        return self._httpd.records  # type: ignore[attr-defined]

    @property
    def captured_paths(self) -> list[str]:
        return [record.path for record in self.captured]


@pytest.fixture
def capture_server() -> Iterator[CaptureServer]:
    """Yield a running loopback HTTP server that records OTLP exports."""
    with CaptureServer() as server:
        yield server
