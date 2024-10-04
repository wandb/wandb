import os
from copy import copy
from unittest import mock

import pytest
import wandb
import wandb.analytics
import wandb.env
from sentry_relay import MetricRelayServer
from sentry_sdk.utils import sentry_sdk
from tests.unit_tests.test_analytics.sentry_relay import SentryResponse

SENTRY_DSN_FORMAT = "http://{key}@127.0.0.1:{port}/{project}"


@pytest.fixture(scope="module")
def relay():
    relay_server = MetricRelayServer()
    relay_server.start()

    yield relay_server

    relay_server.stop()


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
    This test ensures no events are sent to sentry when the wandb sentry client is disabled.

    The test sets the `ERROR_REPORTING` environment variable to `false` and initializes the wandb sentry client.
    """
    wandb_sentry_message = "wandb sentry message"
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
        wandb_sentry_event_id = wandb_sentry.message(wandb_sentry_message)

        # When wandb sentry is disabled, the _safe_noop wrapper function always returns `None`
        assert wandb_sentry.scope is None
        assert wandb_sentry_event_id is None


def test_wandb_sentry_init_after_client_init(relay):
    """
    This test ensures proper isolation between the Sentry instances initialized by another client and by wandb's client.

    This test initializes the Sentry client first using `sentry_sdk.init()`, follwed by initializing wandb's Sentry client.
    Both instances contain unique sessions and tags
    """
    expected_other_sentry_response = SentryResponse(
        message="other sentry message",
        project_id="654321",
        public_key="OTHER_SENTRY_PUBLIC_KEY",
        tags={"test": "tag"},
    )
    expected_wandb_sentry_response = SentryResponse(
        message="wandb sentry message",
        project_id="123456",
        public_key="WANDB_SENTRY_PUBLIC_KEY",
    )
    with mock.patch.dict(
        os.environ,
        {
            wandb.env.ERROR_REPORTING: "true",
            wandb.env.SENTRY_DSN: SENTRY_DSN_FORMAT.format(
                key=expected_wandb_sentry_response.public_key,
                port=relay.port,
                project=expected_wandb_sentry_response.project_id,
            ),
        },
    ):
        sentry_sdk.init(
            dsn=SENTRY_DSN_FORMAT.format(
                key=expected_other_sentry_response.public_key,
                port=relay.port,
                project=expected_other_sentry_response.project_id,
            ),
            default_integrations=False,
        )
        wandb_sentry = wandb.analytics.Sentry()
        wandb_sentry.setup()

        sentry_sdk.set_tag("test", "tag")
        wandb_sentry.configure_scope(tags={"entity": "tag"})
        expected_wandb_sentry_response.tags = wandb_sentry.scope._tags

        # Send sentry events
        other_sentry_event_id = sentry_sdk.capture_message(
            expected_other_sentry_response.message
        )
        wandb_sentry_event_id = wandb_sentry.message(
            expected_wandb_sentry_response.message
        )

        relay.wait_for_events([other_sentry_event_id, wandb_sentry_event_id])

        wandb_sentry_envelope = relay.events[wandb_sentry_event_id]
        other_sentry_envelope = relay.events[other_sentry_event_id]

        # Assert no data is leaked between wandb and other sentry clients
        assert wandb_sentry_envelope != other_sentry_envelope

        # Assert expected data is sent to sentry
        assert wandb_sentry_envelope == expected_wandb_sentry_response
        assert other_sentry_envelope == expected_other_sentry_response


def test_wandb_sentry_init_after_client_write(relay):
    """
    This test ensures proper isolation between the Sentry instances initialized by another client and by wandb's client.
    Even after events have already been sent to Sentry by the other Sentry client.

    This test initializes the Sentry client first using `sentry_sdk.init()` and sends a message to Sentry.
    Then wandb's Sentry client is initialized, and sends a message to Sentry.
    """
    expected_other_sentry_response = SentryResponse(
        message="other sentry message",
        project_id="654321",
        public_key="OTHER_SENTRY_PUBLIC_KEY",
        tags={"test": "tag"},
    )
    expected_wandb_sentry_response = SentryResponse(
        message="wandb sentry message",
        project_id="123456",
        public_key="WANDB_SENTRY_PUBLIC_KEY",
    )
    with mock.patch.dict(
        os.environ,
        {
            wandb.env.ERROR_REPORTING: "true",
            wandb.env.SENTRY_DSN: SENTRY_DSN_FORMAT.format(
                key=expected_wandb_sentry_response.public_key,
                port=relay.port,
                project=expected_wandb_sentry_response.project_id,
            ),
        },
    ):
        sentry_sdk.init(
            dsn=SENTRY_DSN_FORMAT.format(
                key=expected_other_sentry_response.public_key,
                port=relay.port,
                project=expected_other_sentry_response.project_id,
            ),
            default_integrations=False,
        )
        sentry_sdk.set_tag("test", "tag")

        # Send client sentry events
        other_sentry_event_id = sentry_sdk.capture_message(
            expected_other_sentry_response.message
        )

        # Init wandb sentry and send events
        wandb_sentry = wandb.analytics.Sentry()
        wandb_sentry.setup()
        wandb_sentry.configure_scope(tags={"entity": "tag"})
        expected_wandb_sentry_response.tags = wandb_sentry.scope._tags
        wandb_sentry_event_id = wandb_sentry.message(
            expected_wandb_sentry_response.message
        )

        relay.wait_for_events([other_sentry_event_id, wandb_sentry_event_id])

        wandb_sentry_envelope = relay.events[wandb_sentry_event_id]
        other_sentry_envelope = relay.events[other_sentry_event_id]

        # Assert no data is leaked between wandb and other sentry clients
        assert wandb_sentry_envelope != other_sentry_envelope

        # Assert expected data is sent to sentry
        assert wandb_sentry_envelope == expected_wandb_sentry_response
        assert other_sentry_envelope == expected_other_sentry_response


def test_wandb_sentry_initialized_first(relay):
    """
    This test ensures proper isolation between the Sentry instances initialized by another client and by wandb's client.
    When the wandb Sentry client is initialized before the other Sentry client.

    This test initializes the wandb Sentry client first.
    Followed by initializing the other Sentry client using `sentry_sdk.init()`.
    """
    expected_other_sentry_response = SentryResponse(
        message="other sentry message",
        project_id="654321",
        public_key="OTHER_SENTRY_PUBLIC_KEY",
        tags={"test": "tag"},
    )
    expected_wandb_sentry_response = SentryResponse(
        message="wandb sentry message",
        project_id="123456",
        public_key="WANDB_SENTRY_PUBLIC_KEY",
    )
    with mock.patch.dict(
        os.environ,
        {
            wandb.env.ERROR_REPORTING: "true",
            wandb.env.SENTRY_DSN: SENTRY_DSN_FORMAT.format(
                key=expected_wandb_sentry_response.public_key,
                port=relay.port,
                project=expected_wandb_sentry_response.project_id,
            ),
        },
    ):
        wandb_sentry = wandb.analytics.Sentry()
        wandb_sentry.setup()
        wandb_sentry.configure_scope(tags={"entity": "tag"})
        expected_wandb_sentry_response.tags = wandb_sentry.scope._tags

        sentry_sdk.init(
            dsn=SENTRY_DSN_FORMAT.format(
                key=expected_other_sentry_response.public_key,
                port=relay.port,
                project=expected_other_sentry_response.project_id,
            ),
            default_integrations=False,
        )
        sentry_sdk.set_tag("test", "tag")

        # Send sentry events
        other_sentry_event_id = sentry_sdk.capture_message(
            expected_other_sentry_response.message
        )
        wandb_sentry_event_id = wandb_sentry.message(
            expected_wandb_sentry_response.message
        )

        relay.wait_for_events([other_sentry_event_id, wandb_sentry_event_id])

        wandb_sentry_envelope = relay.events[wandb_sentry_event_id]
        other_sentry_envelope = relay.events[other_sentry_event_id]

        # Assert no data is leaked between wandb and other sentry clients
        assert wandb_sentry_envelope != other_sentry_envelope

        # Assert expected data is sent to sentry
        assert wandb_sentry_envelope == expected_wandb_sentry_response
        assert other_sentry_envelope == expected_other_sentry_response


def test_wandb_sentry_write_first(relay):
    """
    This test ensures proper isolation between the Sentry instances initialized by another client and by wandb's client.
    When the wandb Sentry client is initialized and sends an event before the other Sentry client.

    This test initializes the wandb Sentry client first and sends a message to Sentry.
    Followed by initializing the other Sentry client using `sentry_sdk.init()`, and sending a message to Sentry.
    """
    expected_other_sentry_response = SentryResponse(
        message="other sentry message",
        project_id="654321",
        public_key="OTHER_SENTRY_PUBLIC_KEY",
        tags={"test": "tag"},
    )
    expected_wandb_sentry_response = SentryResponse(
        message="wandb sentry message",
        project_id="123456",
        public_key="WANDB_SENTRY_PUBLIC_KEY",
    )
    expected_wandb_sentry_response2 = copy(expected_wandb_sentry_response)
    expected_wandb_sentry_response2.message += "2"
    with mock.patch.dict(
        os.environ,
        {
            wandb.env.ERROR_REPORTING: "true",
            wandb.env.SENTRY_DSN: SENTRY_DSN_FORMAT.format(
                key=expected_wandb_sentry_response.public_key,
                port=relay.port,
                project=expected_wandb_sentry_response.project_id,
            ),
        },
    ):
        # Configure and send wandb sentry event before initializing client sentry
        wandb_sentry = wandb.analytics.Sentry()
        wandb_sentry.setup()
        wandb_sentry.configure_scope(tags={"entity": "tag"})
        expected_wandb_sentry_response.tags = wandb_sentry.scope._tags
        expected_wandb_sentry_response2.tags = wandb_sentry.scope._tags

        wandb_sentry_event_id = wandb_sentry.message(
            expected_wandb_sentry_response.message
        )

        sentry_sdk.init(
            dsn=SENTRY_DSN_FORMAT.format(
                key=expected_other_sentry_response.public_key,
                port=relay.port,
                project=expected_other_sentry_response.project_id,
            ),
            default_integrations=False,
        )
        sentry_sdk.set_tag("test", "tag")

        # Send sentry events
        other_sentry_event_id = sentry_sdk.capture_message(
            expected_other_sentry_response.message
        )
        wandb_sentry_event_id2 = wandb_sentry.message(
            expected_wandb_sentry_response.message + "2"
        )

        relay.wait_for_events(
            [other_sentry_event_id, wandb_sentry_event_id, wandb_sentry_event_id2]
        )

        wandb_sentry_envelope = relay.events[wandb_sentry_event_id]
        wandb_sentry_envelope2 = relay.events[wandb_sentry_event_id2]
        other_sentry_envelope = relay.events[other_sentry_event_id]

        # Assert no data is leaked between wandb and other sentry clients
        assert wandb_sentry_envelope != other_sentry_envelope
        assert wandb_sentry_envelope2 != other_sentry_envelope

        # Assert expected data is sent to sentry
        assert wandb_sentry_envelope == expected_wandb_sentry_response
        assert wandb_sentry_envelope2 == expected_wandb_sentry_response2
        assert other_sentry_envelope == expected_other_sentry_response


def test_wandb_sentry_exception(relay):
    """
    This test ensures proper isolation between the Sentry instances initialized by another client and by wandb's client.
    In the event that a client sends an exception event to Sentry.

    This test initializes the Sentry client first using `sentry_sdk.init()`, follwed by initializing wandb's Sentry client.
    After, both clients send an exception event to Sentry.
    """
    expected_other_sentry_response = SentryResponse(
        message="other sentry message",
        project_id="654321",
        public_key="OTHER_SENTRY_PUBLIC_KEY",
        tags={"test": "tag"},
        is_error=True,
    )
    expected_wandb_sentry_response = SentryResponse(
        message="wandb sentry message",
        project_id="123456",
        public_key="WANDB_SENTRY_PUBLIC_KEY",
        is_error=True,
    )

    with mock.patch.dict(
        os.environ,
        {
            wandb.env.ERROR_REPORTING: "true",
            wandb.env.SENTRY_DSN: SENTRY_DSN_FORMAT.format(
                key=expected_wandb_sentry_response.public_key,
                port=relay.port,
                project=expected_wandb_sentry_response.project_id,
            ),
        },
    ):
        sentry_sdk.init(
            dsn=SENTRY_DSN_FORMAT.format(
                key=expected_other_sentry_response.public_key,
                port=relay.port,
                project=expected_other_sentry_response.project_id,
            ),
            default_integrations=False,
        )
        wandb_sentry = wandb.analytics.Sentry()
        wandb_sentry.setup()

        # Send sentry events
        sentry_sdk.set_tag("test", "tag")
        wandb_sentry.configure_scope(tags={"entity": "tag"})
        expected_wandb_sentry_response.tags = wandb_sentry.scope._tags
        other_sentry_event_id = sentry_sdk.capture_exception(
            Exception(expected_other_sentry_response.message)
        )
        wandb_sentry_event_id = wandb_sentry.exception(
            Exception(expected_wandb_sentry_response.message)
        )

        relay.wait_for_events([other_sentry_event_id, wandb_sentry_event_id])

        wandb_sentry_envelope = relay.events[wandb_sentry_event_id]
        other_sentry_envelope = relay.events[other_sentry_event_id]

        # Assert no data is leaked between wandb and other sentry clients
        assert wandb_sentry_envelope != other_sentry_envelope

        # Assert expected data is sent to sentry
        assert wandb_sentry_envelope == expected_wandb_sentry_response
        assert other_sentry_envelope == expected_other_sentry_response
