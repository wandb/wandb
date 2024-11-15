from __future__ import annotations

import gzip
import socket
import threading
import time
from typing import Any

import flask
import requests
from flask import request
from sentry_sdk.envelope import Envelope


class SentryResponse:
    def __init__(
        self,
        message: str | None,
        project_id: str,
        public_key: str,
        tags: None | dict[str, Any] = None,
        is_error: bool = False,
        stacktrace: None | dict[str, Any] = None,
    ):
        self.message = message
        self.project_id = project_id
        self.public_key = public_key
        self.tags = tags
        self.stacktrace = stacktrace
        self.is_error = is_error

    def __eq__(self, other):
        return (
            self.message == other.message
            and self.project_id == other.project_id
            and self.public_key == other.public_key
            and self.tags == other.tags
            and self.is_error == other.is_error
        )


class MetricRelayServer:
    """
    A mock Sentry Relay server that listens for local requests to sentry APIs.
    These local requests are stored in a dictionary of event_id to SentryResponse.
    """

    events: dict = {}

    def __init__(
        self,
    ) -> None:
        self.is_running = False
        self.port = self._get_free_port()
        self.app = flask.Flask(__name__)
        self.app.add_url_rule(
            rule="/api/<project_id>/envelope/",
            methods=["POST"],
            view_func=self.sentry,
        )
        self.app.add_url_rule(
            rule="/ping/",
            methods=["GET"],
            view_func=self.ping,
        )

        self._sentry_responses = []

    def start(self) -> None:
        # run server in a separate thread
        self.relay_server_thread = threading.Thread(
            target=self.app.run,
            kwargs={
                "port": self.port,
            },
            daemon=True,
        )
        self.relay_server_thread.start()

        # wait for server to start
        while not self.is_running:
            try:
                requests.get(f"http://127.0.0.1:{self.port}/ping/")
                self.is_running = True
            except BaseException:
                continue

    def stop(self) -> None:
        # Adding a timeout to the thread to instantly stop the server
        # Since flask dose not expose an API to stop the server.
        # TODO: replace this with a proper shutdown mechanism
        # https://werkzeug.palletsprojects.com/en/3.0.x/serving/#shutting-down-the-server
        self.relay_server_thread.join(0)

    @staticmethod
    def _get_free_port() -> int:
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        _, port = sock.getsockname()
        return port

    def wait_for_events(self, event_ids, timeout=5):
        start_time = time.time()
        end_time = start_time + timeout

        while (
            not all(event_id in self.events for event_id in event_ids)
            and time.time() < end_time
        ):
            time.sleep(0.1)

        for event_id in event_ids:
            assert event_id in self.events

    def sentry(self, project_id: str):
        # Data sent to sentry is compressed with gzip
        # We need to decompress the request data to read the contents
        decompressed_data = gzip.decompress(request.get_data())
        envelope = Envelope.deserialize(decompressed_data)  # type: Envelope
        payload = envelope.items[0].payload.json

        assert payload is not None

        is_error = "exception" in payload
        if is_error:
            message = (
                payload["exception"]["values"][0]["value"]
                if len(payload["exception"]["values"]) > 0
                else None
            )
            stacktrace = payload["exception"]["values"][0]["stacktrace"]
        else:
            message = payload["message"]
            stacktrace = None

        self.events[envelope.headers["event_id"]] = SentryResponse(
            message=message,
            project_id=project_id,
            public_key=envelope.headers["trace"]["public_key"],
            tags=payload["tags"],
            is_error=is_error,
            stacktrace=stacktrace,
        )
        return "OK"

    def ping(self):
        return "OK"
