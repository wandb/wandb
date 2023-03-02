import contextlib
import dataclasses
import http.server
import os
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
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Hello, world!")

    httpd = http.server.HTTPServer(("localhost", 0), MyServer)
    httpd.socket = ssl.wrap_socket(
        httpd.socket,
        keyfile=ssl_creds.key,
        certfile=ssl_creds.cert,
        server_side=True,
    )

    threading.Thread(target=httpd.serve_forever, daemon=True).start()

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
        assert requests.get(url).status_code == 200


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
        print(os.environ)
        assert requests.get(url).status_code == 200
