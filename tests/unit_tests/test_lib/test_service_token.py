from __future__ import annotations

import os
import pathlib
import socket

import pytest
from wandb.sdk.lib import asyncio_manager
from wandb.sdk.lib.service import ipc_support, service_token


@pytest.fixture
def chdir_to_tmp_path(tmp_path):
    cwd = pathlib.Path.cwd()

    os.chdir(tmp_path)
    try:
        yield
    finally:
        os.chdir(cwd)


@pytest.fixture(scope="module")
def asyncer():
    asyncer = asyncio_manager.AsyncioManager()
    asyncer.start()

    try:
        yield asyncer
    finally:
        asyncer.join()


@pytest.mark.skipif(
    not ipc_support.SUPPORTS_UNIX,
    reason="AF_UNIX sockets not supported",
)
def test_unix_token(asyncer, chdir_to_tmp_path):
    # Unix socket paths are limited to ~100 characters, and tmp_path can be
    # too long on some systems. So instead, we cd into it and use a relative
    # path as the socket name.
    _ = chdir_to_tmp_path

    unix_listener = socket.socket(socket.AF_UNIX)
    unix_listener.bind("socket")
    unix_listener.listen(1)
    with unix_listener:
        token = service_token.UnixServiceToken(parent_pid=123, path="socket")

        # Connection should succeed.
        client = token.connect(asyncer=asyncer)
        asyncer.run(client.close)


def test_tcp_token(asyncer):
    tcp_listener = socket.socket(socket.AF_INET)
    tcp_listener.bind(("127.0.0.1", 0))
    tcp_listener.listen(1)
    with tcp_listener:
        _, port = tcp_listener.getsockname()
        token = service_token.TCPServiceToken(parent_pid=123, port=port)

        # Connection should succeed.
        client = token.connect(asyncer=asyncer)
        asyncer.run(client.close)
