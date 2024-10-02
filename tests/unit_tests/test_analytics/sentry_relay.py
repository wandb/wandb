import socket
import threading
import zlib

import flask
import requests
from flask import request
from sentry_sdk.envelope import Envelope


class SentryResponse:
    def __init__(
        self,
        payload,
        project_id,
        public_key,
        tags,
    ):
        self.payload = payload
        self.project_id = project_id
        self.public_key = public_key
        self.tags = tags


class MetricRelayServer:
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
        self.relay_url = f"http://127.0.0.1:{self.port}"

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
                requests.get(f"{self.relay_url}/ping/")
                self.is_running = True
            except BaseException:
                continue

        self.is_running = True

    def stop(self) -> None:
        # Adding a timeout to the thread to instantly stop the server
        # Since flask dose not expose an API to stop the server.
        self.relay_server_thread.join(0)

    @staticmethod
    def _get_free_port() -> int:
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        _, port = sock.getsockname()
        return port

    def extract_sentry_message_details(self, event_data):
        decompressed_data = zlib.decompress(event_data, 16 + zlib.MAX_WBITS)
        envelope = Envelope.deserialize(decompressed_data)
        return envelope

    def sentry(self, project_id):
        decompressed_data = zlib.decompress(request.get_data(), 16 + zlib.MAX_WBITS)
        envelope = Envelope.deserialize(decompressed_data)  # type: Envelope
        payload = envelope.items[0].payload.json
        self.events[envelope.headers["event_id"]] = SentryResponse(
            payload=payload,
            project_id=project_id,
            public_key=envelope.headers["trace"]["public_key"],
            tags=payload["tags"],
        )
        return "OK"

    def ping(self):
        return "OK"
