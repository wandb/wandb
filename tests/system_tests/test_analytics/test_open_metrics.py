from sentry_sdk.utils import sentry_sdk
from contextlib import contextmanager
from collections import defaultdict
import os
import zlib
from tests.system_tests.relay import RelayServer
import wandb
import json
import socket
import flask
import pytest
import threading
import time
import unittest.mock
from typing import Any, Dict, Iterator, List, Optional, Union

EXTERNAL_SENTRY_DSN_KEY = "EXTERNALKEY"
EXTERNAL_SENTRY_PROJECT = "123456789"

@pytest.fixture
def relay_server():
    pytest._relay_server = MetricRelayServer()
    pytest._relay_server.start()


class MetricRelayServer:
    def __init__(
        self,
    ) -> None:
        self.app = flask.Flask(__name__)
        self.app.add_url_rule(
            rule="/api/<projectId>/envelope/",
            methods=["POST", "PUT", "GET"],
            view_func=self.sentry,
        )
        self.port = self._get_free_port()
        self.relay_url = f"http://127.0.0.1:{self.port}"
        self._sentry_responses = []


    @staticmethod
    def _get_free_port() -> int:
        sock = socket.socket()
        sock.bind(("", 0))

        _, port = sock.getsockname()
        return port


    def start(self) -> None:
        # run server in a separate thread
        relay_server_thread = threading.Thread(
            target=self.app.run,
            kwargs={"port": self.port},
            daemon=True,
        )
        relay_server_thread.start()


    def sentry(self, projectId):
        print(f'projectId: {projectId}')
        request = flask.request
        decompressed_data = zlib.decompress(request.get_data(), 16+zlib.MAX_WBITS)
        json_string = decompressed_data.decode('utf-8').strip()
        json_strings = json_string.split('\n')
        self._sentry_responses.append(projectId)

        # app.logger.info(f'data: {json_strings[1]}')
        return "Hello"


def test_recordMessage(relay_server):
    # with relay_server() as relay:
    print(f'Runnning test')
    port = pytest._relay_server.port

    sentry_sdk.init(
            dsn=f"http://EXTERNALKEY@127.0.0.1:{port}/123456",
        traces_sample_rate=1.0,
        profiles_sample_rate=1.0,
    )
    sentry_sdk.capture_message(f"external sentry message")
    # assert len(relay._sentry_responses) >= 1
        # time.sleep(5)
    
        # print(f'relay response: {relay._sentry_responses}')
        # sentry_client = sentry_sdk.get_client()


        # wandb_init(key='local-87eLxjoRhY6u2ofg63NAJo7rVYHZo4NGACOvpSsF')
        # wandb._sentry.setup()
        # wandb_client = wandb._sentry.scope.client # type: ignore

        # assert sentry_client != wandb_client
