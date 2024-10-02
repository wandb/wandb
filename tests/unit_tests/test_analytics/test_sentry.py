import os
from unittest import mock

import pytest
import wandb
import wandb.analytics
import wandb.env
from sentry_relay import MetricRelayServer
from sentry_sdk.utils import sentry_sdk

SENTRY_DSN_FORMAT = "http://{key}@127.0.0.1:{port}/{project}"


@pytest.fixture(scope="module")
def relay():
    relay_server = MetricRelayServer()
    relay_server.start()

    yield relay_server

    relay_server.stop()


# Helps in checking that no data is leaked between wandb sentry events and client sentry events
def assert_wandb_and_client_events(wandb_envelope, client_envelope):
    assert wandb_envelope.public_key != client_envelope.public_key
    assert wandb_envelope.project_id != client_envelope.project_id
    assert wandb_envelope.tags != client_envelope.tags


def test_wandb_sentry_does_not_interfer_with_global_sentry_sdk(relay):
    """
    Test that wandb sentry initialization does not interfere with global sentry_sdk.
    """
    other_sentry_public_key = "OTHER_SENTRY_PUBLIC_KEY"
    other_sentry_project_id = "654321"
    wandb_sentry_public_key = "WANDB_SENTRY_PUBLIC_KEY"
    wandb_sentry_project_id = "123456"
    with mock.patch.dict(
        os.environ,
        {
            wandb.env.ERROR_REPORTING: "true",
            wandb.env.SENTRY_DSN: SENTRY_DSN_FORMAT.format(
                key=wandb_sentry_public_key,
                port=relay.port,
                project=wandb_sentry_project_id,
            ),
        },
    ):
        sentry_sdk.init(
            dsn=SENTRY_DSN_FORMAT.format(
                key=other_sentry_public_key,
                port=relay.port,
                project=other_sentry_project_id,
            ),
            default_integrations=False,
        )
        wandb_sentry = wandb.analytics.Sentry()
        wandb_sentry.setup()

        assert sentry_sdk.get_current_scope() != wandb_sentry.scope
        assert (
            sentry_sdk.get_current_scope().client.dsn != wandb_sentry.scope.client.dsn
        )


def test_wandb_error_reporting_disabled(relay):
    """
    Test that no events are sent when error reporting is disabled.
    """
    wandb_sentry_client_message = "wandb message"
    wandb_sentry_public_key = "WANDB_SENTRY_PUBLIC_KEY"
    wandb_sentry_project_id = "123456"
    with mock.patch.dict(
        os.environ,
        {
            wandb.env.ERROR_REPORTING: "false",
            wandb.env.SENTRY_DSN: SENTRY_DSN_FORMAT.format(
                key=wandb_sentry_public_key,
                port=relay.port,
                project=wandb_sentry_project_id,
            ),
        },
    ):
        wandb_sentry = wandb.analytics.Sentry()
        wandb_sentry.setup()

        wandb_sentry.configure_scope(tags={"entity": "tag"})
        wandb_event_id = wandb_sentry.message(wandb_sentry_client_message)

        try:
            relay.wait_for_events([wandb_event_id], timeout=1)
            raise Exception("No events should have been sent")
        except AssertionError:
            pass


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
    other_sentry_client_message = "client message"
    other_sentry_public_key = "OTHER_SENTRY_PUBLIC_KEY"
    other_sentry_project_id = "654321"
    wandb_sentry_client_message = "wandb message"
    wandb_sentry_public_key = "WANDB_SENTRY_PUBLIC_KEY"
    wandb_sentry_project_id = "123456"
    with mock.patch.dict(
        os.environ,
        {
            wandb.env.ERROR_REPORTING: "true",
            wandb.env.SENTRY_DSN: SENTRY_DSN_FORMAT.format(
                key=wandb_sentry_public_key,
                port=relay.port,
                project=wandb_sentry_project_id,
            ),
        },
    ):
        sentry_sdk.init(
            dsn=SENTRY_DSN_FORMAT.format(
                key=other_sentry_public_key,
                port=relay.port,
                project=other_sentry_project_id,
            ),
            default_integrations=False,
        )
        wandb_sentry = wandb.analytics.Sentry()
        wandb_sentry.setup()

        # Send sentry events
        sentry_sdk.set_tag("test", "tag")
        wandb_sentry.configure_scope(tags={"entity": "tag"})
        client_event_id = sentry_sdk.capture_message(other_sentry_client_message)
        wandb_event_id = wandb_sentry.message(wandb_sentry_client_message)

        relay.wait_for_events([client_event_id, wandb_event_id])

        wandb_sentry_envelope = relay.events[wandb_event_id]
        other_sentry_envelope = relay.events[client_event_id]

        # Assert no data is leaked between wandb and other sentry clients
        assert (
            wandb_sentry_envelope.payload["message"]
            != other_sentry_envelope.payload["message"]
        )
        assert_wandb_and_client_events(wandb_sentry_envelope, other_sentry_envelope)

        # Assert expected data in sentry events
        assert wandb_sentry_envelope.payload["message"] == wandb_sentry_client_message
        assert wandb_sentry_envelope.project_id == wandb_sentry_project_id
        assert wandb_sentry_envelope.public_key == wandb_sentry_public_key

        assert other_sentry_envelope.payload["message"] == other_sentry_client_message
        assert other_sentry_envelope.project_id == other_sentry_project_id
        assert other_sentry_envelope.public_key == other_sentry_public_key


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
    other_sentry_client_message = "client message"
    other_sentry_public_key = "OTHER_SENTRY_PUBLIC_KEY"
    other_sentry_project_id = "654321"
    wandb_sentry_client_message = "wandb message"
    wandb_sentry_public_key = "WANDB_SENTRY_PUBLIC_KEY"
    wandb_sentry_project_id = "123456"
    with mock.patch.dict(
        os.environ,
        {
            wandb.env.ERROR_REPORTING: "true",
            wandb.env.SENTRY_DSN: SENTRY_DSN_FORMAT.format(
                key=wandb_sentry_public_key,
                port=relay.port,
                project=wandb_sentry_project_id,
            ),
        },
    ):
        sentry_sdk.init(
            dsn=SENTRY_DSN_FORMAT.format(
                key=other_sentry_public_key,
                port=relay.port,
                project=other_sentry_project_id,
            ),
            default_integrations=False,
        )
        sentry_sdk.set_tag("test", "tag")

        # Send client sentry events
        client_event_id = sentry_sdk.capture_message(other_sentry_client_message)

        # Init wandb sentry and send events
        wandb_sentry = wandb.analytics.Sentry()
        wandb_sentry.setup()
        wandb_sentry.configure_scope(tags={"entity": "tag"})
        wandb_event_id = wandb_sentry.message(wandb_sentry_client_message)

        relay.wait_for_events([client_event_id, wandb_event_id])

        wandb_sentry_envelope = relay.events[wandb_event_id]
        other_sentry_envelope = relay.events[client_event_id]

        # Assert no data is leaked between wandb and other sentry clients
        assert (
            wandb_sentry_envelope.payload["message"]
            != other_sentry_envelope.payload["message"]
        )
        assert_wandb_and_client_events(wandb_sentry_envelope, other_sentry_envelope)

        # Assert expected data in sentry events
        assert wandb_sentry_envelope.payload["message"] == wandb_sentry_client_message
        assert wandb_sentry_envelope.project_id == wandb_sentry_project_id
        assert wandb_sentry_envelope.public_key == wandb_sentry_public_key

        assert other_sentry_envelope.payload["message"] == other_sentry_client_message
        assert other_sentry_envelope.project_id == other_sentry_project_id
        assert other_sentry_envelope.public_key == other_sentry_public_key


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
    other_sentry_client_message = "client message"
    other_sentry_public_key = "OTHER_SENTRY_PUBLIC_KEY"
    other_sentry_project_id = "654321"
    wandb_sentry_client_message = "wandb message"
    wandb_sentry_public_key = "WANDB_SENTRY_PUBLIC_KEY"
    wandb_sentry_project_id = "123456"
    with mock.patch.dict(
        os.environ,
        {
            wandb.env.ERROR_REPORTING: "true",
            wandb.env.SENTRY_DSN: SENTRY_DSN_FORMAT.format(
                key=wandb_sentry_public_key,
                port=relay.port,
                project=wandb_sentry_project_id,
            ),
        },
    ):
        wandb_sentry = wandb.analytics.Sentry()
        wandb_sentry.setup()
        wandb_sentry.configure_scope(tags={"entity": "tag"})

        sentry_sdk.init(
            dsn=SENTRY_DSN_FORMAT.format(
                key=other_sentry_public_key,
                port=relay.port,
                project=other_sentry_project_id,
            ),
            default_integrations=False,
        )
        sentry_sdk.set_tag("test", "tag")

        # Send sentry events
        client_event_id = sentry_sdk.capture_message(other_sentry_client_message)
        wandb_event_id = wandb_sentry.message(wandb_sentry_client_message)

        relay.wait_for_events([client_event_id, wandb_event_id])

        wandb_sentry_envelope = relay.events[wandb_event_id]
        other_sentry_envelope = relay.events[client_event_id]

        # Assert no data is leaked between wandb and other sentry clients
        assert (
            wandb_sentry_envelope.payload["message"]
            != other_sentry_envelope.payload["message"]
        )
        assert_wandb_and_client_events(wandb_sentry_envelope, other_sentry_envelope)

        # Assert expected data in sentry events
        assert wandb_sentry_envelope.payload["message"] == wandb_sentry_client_message
        assert wandb_sentry_envelope.project_id == wandb_sentry_project_id
        assert wandb_sentry_envelope.public_key == wandb_sentry_public_key

        assert other_sentry_envelope.payload["message"] == other_sentry_client_message
        assert other_sentry_envelope.project_id == other_sentry_project_id
        assert other_sentry_envelope.public_key == other_sentry_public_key


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
    other_sentry_client_message = "client message"
    other_sentry_public_key = "OTHER_SENTRY_PUBLIC_KEY"
    other_sentry_project_id = "654321"
    wandb_sentry_client_message = "wandb message"
    wandb_sentry_public_key = "WANDB_SENTRY_PUBLIC_KEY"
    wandb_sentry_project_id = "123456"
    with mock.patch.dict(
        os.environ,
        {
            wandb.env.ERROR_REPORTING: "true",
            wandb.env.SENTRY_DSN: SENTRY_DSN_FORMAT.format(
                key=wandb_sentry_public_key,
                port=relay.port,
                project=wandb_sentry_project_id,
            ),
        },
    ):
        # Configure and send wandb sentry event before initializing client sentry
        wandb_sentry = wandb.analytics.Sentry()
        wandb_sentry.setup()
        wandb_sentry.configure_scope(tags={"entity": "tag"})
        wandb_event_id = wandb_sentry.message(wandb_sentry_client_message)

        sentry_sdk.init(
            dsn=SENTRY_DSN_FORMAT.format(
                key=other_sentry_public_key,
                port=relay.port,
                project=other_sentry_project_id,
            ),
            default_integrations=False,
        )
        sentry_sdk.set_tag("test", "tag")

        # Send sentry events
        client_event_id = sentry_sdk.capture_message(other_sentry_client_message)
        wandb_event_id2 = wandb_sentry.message(wandb_sentry_client_message + "2")

        relay.wait_for_events([client_event_id, wandb_event_id, wandb_event_id2])

        wandb_sentry_envelope = relay.events[wandb_event_id]
        wandb_sentry_envelope2 = relay.events[wandb_event_id2]
        other_sentry_envelope = relay.events[client_event_id]

        # Assert no data is leaked between wandb and other sentry clients
        assert (
            wandb_sentry_envelope.payload["message"]
            != other_sentry_envelope.payload["message"]
        )
        assert (
            wandb_sentry_envelope2.payload["message"]
            != other_sentry_envelope.payload["message"]
        )
        assert_wandb_and_client_events(wandb_sentry_envelope, other_sentry_envelope)
        assert_wandb_and_client_events(wandb_sentry_envelope2, other_sentry_envelope)

        # Assert expected data in sentry events
        assert wandb_sentry_envelope.payload["message"] == wandb_sentry_client_message
        assert wandb_sentry_envelope.project_id == wandb_sentry_project_id
        assert wandb_sentry_envelope.public_key == wandb_sentry_public_key

        assert (
            wandb_sentry_envelope2.payload["message"]
            == wandb_sentry_client_message + "2"
        )
        assert wandb_sentry_envelope2.project_id == wandb_sentry_project_id
        assert wandb_sentry_envelope2.public_key == wandb_sentry_public_key

        assert other_sentry_envelope.payload["message"] == other_sentry_client_message
        assert other_sentry_envelope.project_id == other_sentry_project_id
        assert other_sentry_envelope.public_key == other_sentry_public_key


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
    other_sentry_client_message = "client message"
    other_sentry_public_key = "OTHER_SENTRY_PUBLIC_KEY"
    other_sentry_project_id = "654321"
    wandb_sentry_client_message = "wandb message"
    wandb_sentry_public_key = "WANDB_SENTRY_PUBLIC_KEY"
    wandb_sentry_project_id = "123456"
    with mock.patch.dict(
        os.environ,
        {
            wandb.env.ERROR_REPORTING: "true",
            wandb.env.SENTRY_DSN: SENTRY_DSN_FORMAT.format(
                key=wandb_sentry_public_key,
                port=relay.port,
                project=wandb_sentry_project_id,
            ),
        },
    ):
        sentry_sdk.init(
            dsn=SENTRY_DSN_FORMAT.format(
                key=other_sentry_public_key,
                port=relay.port,
                project=other_sentry_project_id,
            ),
            default_integrations=False,
        )
        wandb_sentry = wandb.analytics.Sentry()
        wandb_sentry.setup()

        # Send sentry events
        sentry_sdk.set_tag("test", "tag")
        wandb_sentry.configure_scope(tags={"entity": "tag"})
        client_event_id = sentry_sdk.capture_exception(
            Exception(other_sentry_client_message)
        )
        wandb_event_id = wandb_sentry.exception(Exception(wandb_sentry_client_message))

        relay.wait_for_events([client_event_id, wandb_event_id])

        wandb_sentry_envelope = relay.events[wandb_event_id]
        other_sentry_envelope = relay.events[client_event_id]
        wandb_exception_message = wandb_sentry_envelope.payload["exception"]["values"][
            0
        ]["value"]
        other_exception_message = other_sentry_envelope.payload["exception"]["values"][
            0
        ]["value"]

        # Assert no data is leaked between wandb and other sentry clients
        assert wandb_exception_message != other_exception_message
        assert_wandb_and_client_events(wandb_sentry_envelope, other_sentry_envelope)

        # Assert expected data in sentry events
        assert wandb_exception_message == wandb_sentry_client_message
        assert wandb_sentry_envelope.project_id == wandb_sentry_project_id
        assert wandb_sentry_envelope.public_key == wandb_sentry_public_key

        assert other_exception_message == other_sentry_client_message
        assert other_sentry_envelope.project_id == other_sentry_project_id
        assert other_sentry_envelope.public_key == other_sentry_public_key
