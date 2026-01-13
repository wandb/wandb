import contextlib
import dataclasses
import http.server
import ssl
import threading
from pathlib import Path
from typing import Callable, Iterator, Mapping
from unittest.mock import patch

import pytest
import requests
import wandb.apis
import wandb.env


@dataclasses.dataclass
class SSLCredPaths:
    ca_path: Path
    cert: Path
    key: Path


@pytest.fixture(scope="session")
def ssl_creds(assets_path: Callable[[str], Path]) -> SSLCredPaths:
    ca_path = assets_path("ssl_certs")

    # don't hardcode the cert's filename, which has to be the hash of the cert
    [cert_path] = ca_path.glob("*.0")

    return SSLCredPaths(
        ca_path=ca_path,
        cert=cert_path,
        key=ca_path / "localhost.key",
    )


@pytest.fixture(scope="session")
def ssl_server(ssl_creds: SSLCredPaths) -> Iterator[http.server.HTTPServer]:
    class MyServer(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):  # noqa: N802
            body = b"Hello, world!"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()

    httpd = http.server.HTTPServer(("localhost", 0), MyServer)

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=str(ssl_creds.cert), keyfile=str(ssl_creds.key))

    httpd.socket = context.wrap_socket(httpd.socket, server_side=True)

    ready_event = threading.Event()

    def serve_with_signal():
        ready_event.set()
        httpd.serve_forever()

    server_thread = threading.Thread(target=serve_with_signal, daemon=True)
    server_thread.start()

    # Wait for server to signal it's ready
    ready_event.wait(timeout=2.0)

    yield httpd

    httpd.shutdown()


@pytest.mark.parametrize(
    ["env", "expect_disabled"],
    [
        ({}, False),
        ({"WANDB_INSECURE_DISABLE_SSL": ""}, False),
        ({"WANDB_INSECURE_DISABLE_SSL": "false"}, False),
        ({"WANDB_INSECURE_DISABLE_SSL": "true"}, True),
    ],
)
def test_check_ssl_disabled(
    env: Mapping[str, str],
    expect_disabled: bool,
):
    with patch.dict("os.environ", env):
        assert expect_disabled == wandb.env.ssl_disabled()


@contextlib.contextmanager
def disable_ssl_context():
    reset = wandb.apis._disable_ssl()
    try:
        yield
    finally:
        reset()


def test_disable_ssl(
    ssl_server: http.server.HTTPServer,
):
    url = f"https://{ssl_server.server_address[0]}:{ssl_server.server_address[1]}"

    with pytest.raises(requests.exceptions.SSLError):
        requests.get(url)

    with disable_ssl_context():
        with requests.get(url, stream=True) as resp:
            assert resp.status_code == 200


@pytest.mark.parametrize(
    "make_env",
    [
        lambda certpath: {"REQUESTS_CA_BUNDLE": str(certpath)},
        lambda certpath: {"REQUESTS_CA_BUNDLE": str(certpath.parent)},
    ],
)
def test_uses_userspecified_custom_ssl_certs(
    ssl_creds: SSLCredPaths,
    ssl_server: http.server.HTTPServer,
    make_env: Callable[[Path], Mapping[str, str]],
):
    url = f"https://{ssl_server.server_address[0]}:{ssl_server.server_address[1]}"

    with pytest.raises(requests.exceptions.SSLError):
        requests.get(url)

    with patch.dict("os.environ", make_env(ssl_creds.cert)):
        with requests.get(url, stream=True) as resp:
            assert resp.status_code == 200
