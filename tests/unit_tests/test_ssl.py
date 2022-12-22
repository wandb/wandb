import contextlib
import http.server
from pathlib import Path
import ssl
import threading
from typing import Callable, Iterator, Mapping, Type
from unittest.mock import patch

import httpx
import requests
import pytest

import wandb.apis
import wandb.env


@pytest.fixture
def ssl_server(assets_path: Callable[[str], Path]) -> Iterator[http.server.HTTPServer]:

    class MyServer(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Hello, world!")

    httpd = http.server.HTTPServer(("localhost", 0), MyServer)
    httpd.socket = ssl.wrap_socket(
        httpd.socket,
        keyfile=assets_path("wandb.test.key"),
        certfile=assets_path("wandb.test.crt"),
        server_side=True,
    )

    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    yield httpd

    httpd.shutdown()


@pytest.mark.parametrize(
    ["env", "expect_disabled"],
    [
        ({}, False),
        ({"WANDB_INSECURE_DISABLE_SSL": "false"}, False),
        ({"WANDB_INSECURE_DISABLE_SSL": "true"}, True),
    ]
)
def test_check_ssl_disabled(
    env: Mapping[str, str],
    expect_disabled: bool,
):
    with patch.dict("os.environ", env):
        assert expect_disabled == wandb.env.ssl_disabled()


@pytest.mark.parametrize(
    ["get_status", "ssl_errtype"],
    [
        (lambda url: requests.get(url).status_code, requests.exceptions.SSLError),
        (lambda url: httpx.get(url).status_code, httpx.ConnectError),
    ],
)
def test_disable_ssl(
    ssl_server: http.server.HTTPServer,
    get_status: Callable[[str], int],
    ssl_errtype: Type[Exception],
):
    url = f"https://{ssl_server.server_address[0]}:{ssl_server.server_address[1]}"

    with pytest.raises(ssl_errtype):
        get_status(url)

    with wandb.apis._disable_ssl():
        assert get_status(url) == 200
