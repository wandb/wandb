import os
import time
from unittest import mock

import pytest
import wandb
import wandb.analytics
import wandb.env
from sentry_relay import MetricRelayServer
from sentry_sdk.utils import sentry_sdk

EXTERNAL_SENTRY_DSN_KEY = "EXTERNALKEY"
EXTERNAL_SENTRY_PROJECT = "123456"
INTERNAL_SENTRY_DSN_KEY = "INTERNALKEY"
INTERNAL_SENTRY_PROJECT = "654321"
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


@pytest.fixture(scope="module")
def relay():
    relay_server = MetricRelayServer()
    relay_server.start()

    yield relay_server

    relay_server.stop()


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
    assert wandb_envelope.public_key != client_envelope.public_key
    assert wandb_envelope.project_id != client_envelope.project_id
    assert wandb_envelope.tags != client_envelope.tags

    assert wandb_envelope.project_id == INTERNAL_SENTRY_PROJECT
    assert client_envelope.project_id == EXTERNAL_SENTRY_PROJECT

    assert wandb_envelope.public_key == INTERNAL_SENTRY_DSN_KEY
    assert client_envelope.public_key == EXTERNAL_SENTRY_DSN_KEY


def test_wandb_sentry_init_after_client_init(relay):
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
    client_message = "client message"
    wandb_message = "wandb message"
    with mock.patch.dict(
        os.environ,
        {
            wandb.env.ERROR_REPORTING: "true",
            wandb.env.SENTRY_DSN: WANDB_DSN_URL_FORMAT.format(port=relay.port),
        },
    ):
        sentry_sdk.init(
            dsn=EXTERNAL_DSN_URL_FORMAT.format(port=relay.port),
            default_integrations=False,
        )
        wandb_sentry = wandb.analytics.Sentry()
        wandb_sentry.setup()

        # Send sentry events
        sentry_sdk.set_tag("test", "tag")
        wandb_sentry.configure_scope(tags={"entity": "tag"})
        client_event_id = sentry_sdk.capture_message(client_message)
        wandb_event_id = wandb_sentry.message(wandb_message)

        wait_for_events(relay, [client_event_id, wandb_event_id])

        wandb_envelope = relay.events[wandb_event_id]
        client_envelope = relay.events[client_event_id]

        assert wandb_envelope.payload["message"] == wandb_message
        assert client_envelope.payload["message"] == client_message
        assert wandb_envelope.payload["message"] != client_envelope.payload["message"]

        assert_wandb_and_client_events(wandb_envelope, client_envelope)


def test_wandb_sentry_init_after_client_write(relay):
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
    client_message = "client message"
    wandb_message = "wandb message"
    with mock.patch.dict(
        os.environ,
        {
            wandb.env.ERROR_REPORTING: "true",
            wandb.env.SENTRY_DSN: WANDB_DSN_URL_FORMAT.format(port=relay.port),
        },
    ):
        sentry_sdk.init(
            dsn=EXTERNAL_DSN_URL_FORMAT.format(port=relay.port),
            default_integrations=False,
        )
        sentry_sdk.set_tag("test", "tag")

        # Send client sentry events
        client_event_id = sentry_sdk.capture_message(client_message)

        # Init wandb sentry and send events
        wandb_sentry = wandb.analytics.Sentry()
        wandb_sentry.setup()
        wandb_sentry.configure_scope(tags={"entity": "tag"})
        wandb_event_id = wandb_sentry.message(wandb_message)

        wait_for_events(relay, [client_event_id, wandb_event_id])

        wandb_envelope = relay.events[wandb_event_id]
        client_envelope = relay.events[client_event_id]

        wandb_envelope = relay.events[wandb_event_id]
        client_envelope = relay.events[client_event_id]

        assert wandb_envelope.payload["message"] == wandb_message
        assert client_envelope.payload["message"] == client_message
        assert wandb_envelope.payload["message"] != client_envelope.payload["message"]

        assert_wandb_and_client_events(wandb_envelope, client_envelope)


def test_wandb_sentry_initialized_first(relay):
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
    client_message = "client message"
    wandb_message = "wandb message"
    with mock.patch.dict(
        os.environ,
        {
            wandb.env.ERROR_REPORTING: "true",
            wandb.env.SENTRY_DSN: WANDB_DSN_URL_FORMAT.format(port=relay.port),
        },
    ):
        wandb_sentry = wandb.analytics.Sentry()
        wandb_sentry.setup()
        wandb_sentry.configure_scope(tags={"entity": "tag"})

        sentry_sdk.init(
            dsn=EXTERNAL_DSN_URL_FORMAT.format(port=relay.port),
            default_integrations=False,
        )
        sentry_sdk.set_tag("test", "tag")

        # Send sentry events
        client_event_id = sentry_sdk.capture_message(client_message)
        wandb_event_id = wandb_sentry.message(wandb_message)

        wait_for_events(relay, [client_event_id, wandb_event_id])

        wandb_envelope = relay.events[wandb_event_id]
        client_envelope = relay.events[client_event_id]

        assert wandb_envelope.payload["message"] == wandb_message
        assert client_envelope.payload["message"] == client_message
        assert wandb_envelope.payload["message"] != client_envelope.payload["message"]

        assert_wandb_and_client_events(wandb_envelope, client_envelope)


def test_wandb_sentry_write_first(relay):
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
    client_message = "client message"
    wandb_message = "wandb message"
    with mock.patch.dict(
        os.environ,
        {
            wandb.env.ERROR_REPORTING: "true",
            wandb.env.SENTRY_DSN: WANDB_DSN_URL_FORMAT.format(port=relay.port),
        },
    ):
        # Configure and send wandb sentry event before initializing client sentry
        wandb_sentry = wandb.analytics.Sentry()
        wandb_sentry.setup()
        wandb_sentry.configure_scope(tags={"entity": "tag"})
        wandb_event_id = wandb_sentry.message(wandb_message)

        sentry_sdk.init(
            dsn=EXTERNAL_DSN_URL_FORMAT.format(port=relay.port),
            default_integrations=False,
        )
        sentry_sdk.set_tag("test", "tag")

        # Send sentry events
        client_event_id = sentry_sdk.capture_message(client_message)
        wandb_event_id2 = wandb_sentry.message(wandb_message + "2")

        wait_for_events(relay, [client_event_id, wandb_event_id, wandb_event_id2])

        wandb_envelope = relay.events[wandb_event_id]
        wandb_envelope2 = relay.events[wandb_event_id2]
        client_envelope = relay.events[client_event_id]

        assert wandb_envelope.payload["message"] == wandb_message
        assert wandb_envelope2.payload["message"] == wandb_message + "2"
        assert client_envelope.payload["message"] == client_message
        assert wandb_envelope.payload["message"] != client_envelope.payload["message"]
        assert wandb_envelope2.payload["message"] != client_envelope.payload["message"]

        assert_wandb_and_client_events(wandb_envelope, client_envelope)
        assert_wandb_and_client_events(wandb_envelope2, client_envelope)


def test_wandb_sentry_exception(relay):
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
    client_message = "client message"
    wandb_message = "wandb message"
    with mock.patch.dict(
        os.environ,
        {
            wandb.env.ERROR_REPORTING: "true",
            wandb.env.SENTRY_DSN: WANDB_DSN_URL_FORMAT.format(port=relay.port),
        },
    ):
        sentry_sdk.init(
            dsn=EXTERNAL_DSN_URL_FORMAT.format(port=relay.port),
            default_integrations=False,
        )
        wandb_sentry = wandb.analytics.Sentry()
        wandb_sentry.setup()

        # Send sentry events
        sentry_sdk.set_tag("test", "tag")
        wandb_sentry.configure_scope(tags={"entity": "tag"})
        client_event_id = sentry_sdk.capture_exception(Exception(client_message))
        wandb_event_id = wandb_sentry.exception(Exception(wandb_message))

        wait_for_events(relay, [client_event_id, wandb_event_id])

        wandb_envelope = relay.events[wandb_event_id]
        client_envelope = relay.events[client_event_id]
        wandb_exception_message = wandb_envelope.payload["exception"]["values"][0][
            "value"
        ]
        client_exception_message = client_envelope.payload["exception"]["values"][0][
            "value"
        ]

        assert wandb_exception_message == wandb_message
        assert client_exception_message == client_message
        assert wandb_exception_message != client_exception_message

        assert_wandb_and_client_events(
            relay.events[wandb_event_id], relay.events[client_event_id]
        )
