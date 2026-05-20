"""Fixtures for API tests."""

from __future__ import annotations

import http.server
import io
import re
import socket
import socketserver
import threading
from collections.abc import Generator

import pyarrow as pa
import pyarrow.parquet as pq
import pytest


class ParquetFileHandler(http.server.SimpleHTTPRequestHandler):
    """HTTP handler that serves parquet files from memory."""

    parquet_files: dict[str, bytes] = {}

    def do_HEAD(self):
        path = self.path.lstrip("/")

        if path not in self.parquet_files:
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            return

        content = self.parquet_files[path]
        self.send_response(200)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()

    def do_GET(self):
        path = self.path.lstrip("/")

        if path not in self.parquet_files:
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"File not found")
            return

        content = self.parquet_files[path]
        range_header = self.headers.get("Range")

        if range_header is None:
            self.send_response(200)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            self.wfile.write(content)
            return

        match = re.fullmatch(r"bytes=(\d+)-(\d*)", range_header.strip())
        if not match:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{len(content)}")
            self.end_headers()
            return

        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) else len(content) - 1
        end = min(end, len(content) - 1)

        if start > end or start >= len(content):
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{len(content)}")
            self.end_headers()
            return

        partial = content[start : end + 1]
        self.send_response(206)
        self.send_header("Content-Length", str(len(partial)))
        self.send_header("Content-Range", f"bytes {start}-{end}/{len(content)}")
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        self.wfile.write(partial)


class ParquetHTTPServer:
    """Simple HTTP server for serving parquet files over HTTP."""

    def __init__(self):
        self.port = self.get_free_port()
        self.server = None
        self.thread = None

    def get_free_port(self) -> int:
        """Get a free port."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("localhost", 0))
            return s.getsockname()[1]

    def serve_data_as_parquet_file(self, path: str, data: dict[str, list]):
        """Coverts the given data to an in-memory parquet file and serves it at the given path.

        Args:
            path: The URL path to serve the parquet file at (e.g., "parquet/1.parquet")
            data: The data to serve as a parquet file.
        """
        table = pa.table(data)
        buffer = io.BytesIO()
        pq.write_table(table, buffer)
        buffer.seek(0)

        ParquetFileHandler.parquet_files[path] = buffer.read()

    def start(self):
        """Starts the HTTP server in a background thread."""
        self.server = socketserver.TCPServer(
            ("", self.port),
            ParquetFileHandler,
            bind_and_activate=False,
        )
        self.server.allow_reuse_address = True
        self.server.server_bind()
        self.server.server_activate()

        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self.thread:
            self.thread.join(timeout=1)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()


def create_sample_parquet_file(
    data: dict[str, list],
) -> bytes:
    """Create a sample parquet file with history data.

    Returns:
        Parquet file content as bytes
    """
    table = pa.table(data)

    # Write to bytes buffer
    buffer = io.BytesIO()
    pq.write_table(table, buffer)
    buffer.seek(0)

    return buffer.read()


@pytest.fixture()
def parquet_file_server() -> Generator[ParquetHTTPServer, None, None]:
    """Pytest fixture that provides an HTTP server for serving parquet files."""
    server = ParquetHTTPServer()
    server.start()

    yield server

    server.stop()
    ParquetFileHandler.parquet_files.clear()
