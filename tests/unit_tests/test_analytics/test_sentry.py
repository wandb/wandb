import os
import socket
import threading
import time
import zlib

import flask
import pytest
import requests
import wandb
import wandb.analytics
import wandb.env
from flask import request
from sentry_sdk.envelope import Envelope
from sentry_sdk.utils import sentry_sdk

EXTERNAL_SENTRY_DSN_KEY = "EXTERNALKEY"
EXTERNAL_SENTRY_PROJECT = "123456"
INTERNAL_SENTRY_DSN_KEY = "INTERNALKEY"
INTERNAL_SENTRY_PROJECT = "654321"
CLIENT_MESSAGE = "client message"
WANDB_MESSAGE = "wandb message"
API_SERVER_ADDRESS = "127.0.0.1:{port}"
SENTRY_DSN_FORMAT = "http://{key}@{address}/{project}"
WANDB_DSN_URL_FORMAT = SENTRY_DSN_FORMAT.format(
    key=INTERNAL_SENTRY_DSN_KEY,
    address=API_SERVER_ADDRESS,
    project=INTERNAL_SENTRY_PROJECT,
)
EXTERNAL_DSN_URL_FORMAT = SENTRY_DSN_FORMAT.format(
    key=EXTERNAL_SENTRY_DSN_KEY,
    address=API_SERVER_ADDRESS,
    project=EXTERNAL_SENTRY_PROJECT,
)


@pytest.fixture(scope="module", autouse=True)
def relay():
    relay_server = MetricRelayServer()
    relay_server.start()

    return relay_server


@pytest.fixture(scope="module", autouse=True)
def setup_env(relay):
    os.environ[wandb.env.ERROR_REPORTING] = "True"
    os.environ[wandb.env.SENTRY_DSN] = WANDB_DSN_URL_FORMAT.format(port=relay.port)


class MetricRelayServer:
    events = {}

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
        relay_server_thread = threading.Thread(
            target=self.app.run,
            kwargs={
                "port": self.port,
            },
            daemon=True,
        )
        relay_server_thread.start()

        # wait for server to start
        while not self.is_running:
            try:
                requests.get(f"{self.relay_url}/ping/")
                self.is_running = True
            except BaseException:
                continue

        self.is_running = True

    @staticmethod
    def _get_free_port() -> int:
        sock = socket.socket()
        sock.bind(("", 0))
        _, port = sock.getsockname()
        return port

    def extract_sentry_message_details(self, event_data):
        decompressed_data = zlib.decompress(event_data, 16 + zlib.MAX_WBITS)
        envelope = Envelope.deserialize(decompressed_data)
        return envelope

    def sentry(self, project_id):
        decompressed_data = zlib.decompress(request.get_data(), 16 + zlib.MAX_WBITS)
        envelope = Envelope.deserialize(decompressed_data)
        self.events[envelope.headers["event_id"]] = {
            "envelope": envelope,
            "project_id": project_id,
        }
        return "OK"

    def ping(self):
        return "OK"


def wait_for_events(relay, event_ids, timeout=5):
    start_time = time.time()
    end_time = start_time + timeout

    while (
        not all(event_id in relay.events for event_id in event_ids)
        and time.time() < end_time
    ):
        time.sleep(0.1)

    for event_id in event_ids:
        assert event_id in relay.events


# Helps in checking that no data is leaked between wandb sentry events and client sentry events
def assert_wandb_and_client_events(wandb_envelope, client_envelope):
    wandb_public_key = wandb_envelope["envelope"].headers["trace"]["public_key"]
    wandb_payload = wandb_envelope["envelope"].items[0].payload.json
    wandb_project_id = wandb_envelope["project_id"]
    wandb_tags = wandb_payload["tags"]

    client_public_key = client_envelope["envelope"].headers["trace"]["public_key"]
    client_payload = client_envelope["envelope"].items[0].payload.json
    client_project_id = client_envelope["project_id"]
    client_tags = client_payload["tags"]

    assert wandb_public_key != client_public_key
    assert wandb_project_id != client_project_id
    assert wandb_tags != client_tags

    assert wandb_project_id == INTERNAL_SENTRY_PROJECT
    assert client_project_id == EXTERNAL_SENTRY_PROJECT

    assert wandb_public_key == INTERNAL_SENTRY_DSN_KEY
    assert client_public_key == EXTERNAL_SENTRY_DSN_KEY


def assert_messages_not_equal(wandb_message, client_message):
    assert wandb_message != client_message


"""
Tests initializning wandb sentry scope after the client has already initialized sentry.
- Initialize sentry client as a client calling `sentry_sdk.init()`
- Initialize wandb sentry as a client calling `wandb.analytics.Sentry()` and then calling `setup()`
- Add sentry session tags for both client and wandb
- Send sentry event as a client
- Send sentry event from wandb
- Assert events arrive to local api server
- Validate no data is leaked between wandb and client events
"""


def test_wandbsentry_initafterclientinit(relay):
    sentry_sdk.init(
        dsn=EXTERNAL_DSN_URL_FORMAT.format(port=relay.port), default_integrations=False
    )
    wandb_sentry = wandb.analytics.Sentry()
    wandb_sentry.setup()

    # Send sentry events
    sentry_sdk.set_tag("test", "tag")
    wandb_sentry.configure_scope(tags={"entity": "tag"})
    client_event_id = sentry_sdk.capture_message(CLIENT_MESSAGE)
    wandb_event_id = wandb_sentry.message(WANDB_MESSAGE)

    wait_for_events(relay, [client_event_id, wandb_event_id])

    wandb_envelope = relay.events[wandb_event_id]
    client_envelope = relay.events[client_event_id]

    wandb_message = wandb_envelope["envelope"].items[0].payload.json["message"]
    client_message = client_envelope["envelope"].items[0].payload.json["message"]
    assert wandb_message == WANDB_MESSAGE
    assert client_message == CLIENT_MESSAGE
    assert wandb_message != client_message

    assert_wandb_and_client_events(
        relay.events[wandb_event_id], relay.events[client_event_id]
    )


"""
Tests initializning wandb sentry scope after the client has already sent a sentry event.
- Initialize sentry client as a client calling `sentry_sdk.init()`
- Add sentry session tags as client
- Send sentry event as a client
- Initialize wandb sentry as a client calling `wandb.analytics.Sentry()` and then calling `setup()`
- Send sentry event from wandb
- Assert events arrive to local api server
- Validate no data is leaked between wandb and client events
"""


def test_wandbsentry_initafterclientwrite(relay):
    # Setup test
    sentry_sdk.init(
        dsn=EXTERNAL_DSN_URL_FORMAT.format(port=relay.port), default_integrations=False
    )
    sentry_sdk.set_tag("test", "tag")

    # Send client sentry events
    client_event_id = sentry_sdk.capture_message(CLIENT_MESSAGE)

    # Init wandb sentry and send events
    wandb_sentry = wandb.analytics.Sentry()
    wandb_sentry.setup()
    wandb_sentry.configure_scope(tags={"entity": "tag"})
    wandb_event_id = wandb_sentry.message(WANDB_MESSAGE)

    wait_for_events(relay, [client_event_id, wandb_event_id])

    wandb_envelope = relay.events[wandb_event_id]
    client_envelope = relay.events[client_event_id]

    wandb_message = wandb_envelope["envelope"].items[0].payload.json["message"]
    client_message = client_envelope["envelope"].items[0].payload.json["message"]
    assert wandb_message == WANDB_MESSAGE
    assert client_message == CLIENT_MESSAGE
    assert wandb_message != client_message

    assert_wandb_and_client_events(
        relay.events[wandb_event_id], relay.events[client_event_id]
    )


"""
Tests initializning wandb sentry scope before client calls `sentry_sdk.init()`.
- Initialize wandb sentry as a client calling `wandb.analytics.Sentry()` and then calling `setup()`
- Add sentry session tags for wandb client
- Initialize sentry client as a client calling `sentry_sdk.init()`
- Add sentry session tags as client
- Send sentry event as a client
- Send sentry event from wandb
- Assert events arrive to local api server
- Validate no data is leaked between wandb and client events
"""


def test_wandbsentry_initializedfirst(relay):
    wandb_sentry = wandb.analytics.Sentry()
    wandb_sentry.setup()
    wandb_sentry.configure_scope(tags={"entity": "tag"})

    sentry_sdk.init(
        dsn=EXTERNAL_DSN_URL_FORMAT.format(port=relay.port), default_integrations=False
    )
    sentry_sdk.set_tag("test", "tag")

    # Send sentry events
    client_event_id = sentry_sdk.capture_message(CLIENT_MESSAGE)
    wandb_event_id = wandb_sentry.message(WANDB_MESSAGE)

    wait_for_events(relay, [client_event_id, wandb_event_id])

    wandb_envelope = relay.events[wandb_event_id]
    client_envelope = relay.events[client_event_id]

    wandb_message = wandb_envelope["envelope"].items[0].payload.json["message"]
    client_message = client_envelope["envelope"].items[0].payload.json["message"]
    assert wandb_message == WANDB_MESSAGE
    assert client_message == CLIENT_MESSAGE
    assert wandb_message != client_message

    assert_wandb_and_client_events(
        relay.events[wandb_event_id], relay.events[client_event_id]
    )


"""
Tests initializning wandb sentry scope before client initializes or sends sentry events.
- Initialize wandb sentry as a client calling `wandb.analytics.Sentry()` and then calling `setup()`
- Add sentry session tags for wandb client
- Send sentry event from wandb
- Initialize sentry client as a client calling `sentry_sdk.init()`
- Add sentry session tags as client
- Send sentry event as a client
- Send second sentry event from wandb
- Assert events arrive to local api server
- Validate no data is leaked between wandb and client events
"""


def test_wandbsentry_writefirst(relay):
    # Configure and send wandb sentry event before initializing client sentry
    wandb_sentry = wandb.analytics.Sentry()
    wandb_sentry.setup()
    wandb_sentry.configure_scope(tags={"entity": "tag"})
    wandb_event_id = wandb_sentry.message(WANDB_MESSAGE)

    sentry_sdk.init(
        dsn=EXTERNAL_DSN_URL_FORMAT.format(port=relay.port), default_integrations=False
    )
    sentry_sdk.set_tag("test", "tag")

    # Send sentry events
    client_event_id = sentry_sdk.capture_message(CLIENT_MESSAGE)
    wandb_event_id2 = wandb_sentry.message(WANDB_MESSAGE + "2")

    wait_for_events(relay, [client_event_id, wandb_event_id, wandb_event_id2])

    wandb_envelope = relay.events[wandb_event_id]
    wandb_envelope2 = relay.events[wandb_event_id2]
    client_envelope = relay.events[client_event_id]

    wandb_message = wandb_envelope["envelope"].items[0].payload.json["message"]
    wandb_message2 = wandb_envelope2["envelope"].items[0].payload.json["message"]
    client_message = client_envelope["envelope"].items[0].payload.json["message"]
    assert wandb_message == WANDB_MESSAGE
    assert wandb_message2 == WANDB_MESSAGE + "2"
    assert client_message == CLIENT_MESSAGE
    assert wandb_message != client_message
    assert wandb_message2 != client_message

    assert_wandb_and_client_events(
        relay.events[wandb_event_id], relay.events[client_event_id]
    )
    assert_wandb_and_client_events(
        relay.events[wandb_event_id2], relay.events[client_event_id]
    )


"""
Tests initializning wandb sentry scope after the client has already initialized sentry and sending an exception event.
- Initialize sentry client as a client calling `sentry_sdk.init()`
- Initialize wandb sentry as a client calling `wandb.analytics.Sentry()` and then calling `setup()`
- Add sentry session tags for both client and wandb
- Send sentry exception as a client
- Send sentry exception from wandb
- Assert exception events arrive to local api server
- Validate no data is leaked between wandb and client events
"""


def test_wandbsentry_exception(relay):
    sentry_sdk.init(
        dsn=EXTERNAL_DSN_URL_FORMAT.format(port=relay.port), default_integrations=False
    )
    wandb_sentry = wandb.analytics.Sentry()
    wandb_sentry.setup()

    # Send sentry events
    sentry_sdk.set_tag("test", "tag")
    wandb_sentry.configure_scope(tags={"entity": "tag"})
    client_event_id = sentry_sdk.capture_exception(Exception(CLIENT_MESSAGE))
    wandb_event_id = wandb_sentry.exception(Exception(WANDB_MESSAGE))

    wait_for_events(relay, [client_event_id, wandb_event_id])

    wandb_envelope = relay.events[wandb_event_id]
    client_envelope = relay.events[client_event_id]
    wandb_message = (
        wandb_envelope["envelope"]
        .items[0]
        .payload.json["exception"]["values"][0]["value"]
    )
    client_message = (
        client_envelope["envelope"]
        .items[0]
        .payload.json["exception"]["values"][0]["value"]
    )
    assert wandb_message == WANDB_MESSAGE
    assert client_message == CLIENT_MESSAGE
    assert wandb_message != client_message

    assert_wandb_and_client_events(
        relay.events[wandb_event_id], relay.events[client_event_id]
    )
