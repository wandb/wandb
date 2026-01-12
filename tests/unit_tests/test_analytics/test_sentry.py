from __future__ import annotations

import os
from unittest import mock

import pytest
import wandb
import wandb.analytics
import wandb.env
from sentry_sdk.utils import sentry_sdk

from .sentry_relay import MetricRelayServer, SentryResponse

SENTRY_DSN_FORMAT = "http://{key}@127.0.0.1:{port}/{project}"


@pytest.fixture(scope="module")
def relay():
    relay_server = MetricRelayServer()
    relay_server.start()

    yield relay_server

    relay_server.stop()


def test_wandb_sentry_does_not_interfer_with_global_sentry_sdk(
    relay: MetricRelayServer,
):
    """
    Test that wandb sentry initialization does not interfere with global sentry_sdk.
    """
    with mock.patch.dict(
        os.environ,
        {
            wandb.env.ERROR_REPORTING: "true",
            wandb.env.SENTRY_DSN: SENTRY_DSN_FORMAT.format(
                key="WANDB_SENTRY_PUBLIC_KEY",
                port=relay.port,
                project="123456",
            ),
        },
    ):
        sentry_sdk.init(
            dsn=SENTRY_DSN_FORMAT.format(
                key="OTHER_SENTRY_PUBLIC_KEY",
                port=relay.port,
                project="654321",
            ),
            default_integrations=False,
        )
        wandb_sentry = wandb.analytics.sentry.Sentry(pid=os.getpid())
        wandb_sentry.start_session()

        # Assert wandb Sentry scope and dsn are different from the other Sentry client
        assert sentry_sdk.get_current_scope() != wandb_sentry.scope
        assert (
            sentry_sdk.get_current_scope().client.dsn != wandb_sentry.scope.client.dsn  # type: ignore
        )


def test_wandb_error_reporting_disabled(relay: MetricRelayServer):
    """
    This test ensures no events are sent to sentry when the wandb sentry client is disabled.

    The test sets the `ERROR_REPORTING` environment variable to `false` and initializes the wandb sentry client.
    """
    with mock.patch.dict(
        os.environ,
        {
            wandb.env.ERROR_REPORTING: "false",
            wandb.env.SENTRY_DSN: SENTRY_DSN_FORMAT.format(
                key="WANDB_SENTRY_PUBLIC_KEY",
                port=relay.port,
                project="123456",
            ),
        },
    ):
        wandb_sentry = wandb.analytics.sentry.Sentry(pid=os.getpid())
        wandb_sentry.configure_scope(tags={"entity": "tag"})
        wandb_sentry_event_id = wandb_sentry.message("wandb sentry message")

        # When wandb sentry is disabled, the _safe_noop wrapper function always returns `None`
        # Assert none is returned when the wandb Sentry client is disabled
        assert wandb_sentry.scope is None
        assert wandb_sentry_event_id is None


def test_wandb_sentry_init_after_client_init(relay: MetricRelayServer):
    """
    This test ensures proper isolation between the Sentry instances initialized by another client and by wandb's client.

    This test initializes the Sentry client first using `sentry_sdk.init()`, followed by initializing wandb's Sentry client.
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
        tags={
            "entity": "tag",
            "python_runtime": "python",
        },
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
        wandb_sentry = wandb.analytics.sentry.Sentry(pid=os.getpid())

        sentry_sdk.set_tag("test", "tag")
        wandb_sentry.configure_scope(tags={"entity": "tag"})

        # Send sentry events
        other_sentry_event_id = sentry_sdk.capture_message(
            expected_other_sentry_response.message  # type: ignore
        )
        wandb_sentry_event_id = wandb_sentry.message(
            expected_wandb_sentry_response.message
        )

        relay.wait_for_events([other_sentry_event_id, wandb_sentry_event_id])

        wandb_sentry_response = relay.events[wandb_sentry_event_id]
        other_sentry_envelope = relay.events[other_sentry_event_id]

        # Assert no data is leaked between wandb and other sentry clients
        assert wandb_sentry_response != other_sentry_envelope

        # Assert expected data is sent to sentry
        assert wandb_sentry_response == expected_wandb_sentry_response
        assert other_sentry_envelope == expected_other_sentry_response


def test_wandb_sentry_init_after_client_write(relay: MetricRelayServer):
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
        tags={
            "entity": "tag",
            "python_runtime": "python",
        },
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
            expected_other_sentry_response.message  # type: ignore
        )

        # Init wandb sentry and send events
        wandb_sentry = wandb.analytics.sentry.Sentry(pid=os.getpid())
        wandb_sentry.configure_scope(tags={"entity": "tag"})
        wandb_sentry_event_id = wandb_sentry.message(
            expected_wandb_sentry_response.message
        )

        relay.wait_for_events([other_sentry_event_id, wandb_sentry_event_id])

        wandb_sentry_response = relay.events[wandb_sentry_event_id]
        other_sentry_envelope = relay.events[other_sentry_event_id]

        # Assert no data is leaked between wandb and other sentry clients
        assert wandb_sentry_response != other_sentry_envelope

        # Assert expected data is sent to sentry
        assert wandb_sentry_response == expected_wandb_sentry_response
        assert other_sentry_envelope == expected_other_sentry_response


def test_wandb_sentry_initialized_first(relay: MetricRelayServer):
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
        tags={
            "entity": "tag",
            "python_runtime": "python",
        },
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
        wandb_sentry = wandb.analytics.sentry.Sentry(pid=os.getpid())
        wandb_sentry.configure_scope(tags={"entity": "tag"})

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
            expected_other_sentry_response.message  # type: ignore
        )
        wandb_sentry_event_id = wandb_sentry.message(
            expected_wandb_sentry_response.message
        )

        relay.wait_for_events([other_sentry_event_id, wandb_sentry_event_id])

        wandb_sentry_response = relay.events[wandb_sentry_event_id]
        other_sentry_envelope = relay.events[other_sentry_event_id]

        # Assert no data is leaked between wandb and other sentry clients
        assert wandb_sentry_response != other_sentry_envelope

        # Assert expected data is sent to sentry
        assert wandb_sentry_response == expected_wandb_sentry_response
        assert other_sentry_envelope == expected_other_sentry_response


def test_wandb_sentry_write_first(relay: MetricRelayServer):
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
    expected_wandb_sentry_responses = [
        SentryResponse(
            message="wandb sentry message",
            project_id="123456",
            public_key="WANDB_SENTRY_PUBLIC_KEY",
            tags={
                "entity": "tag",
                "python_runtime": "python",
            },
        ),
        SentryResponse(
            message="wandb sentry message",
            project_id="123456",
            public_key="WANDB_SENTRY_PUBLIC_KEY",
            tags={
                "entity": "tag",
                "python_runtime": "python",
            },
        ),
    ]
    with mock.patch.dict(
        os.environ,
        {
            wandb.env.ERROR_REPORTING: "true",
            wandb.env.SENTRY_DSN: SENTRY_DSN_FORMAT.format(
                key=expected_wandb_sentry_responses[0].public_key,
                port=relay.port,
                project=expected_wandb_sentry_responses[0].project_id,
            ),
        },
    ):
        # Configure and send wandb sentry event before initializing client sentry
        wandb_sentry = wandb.analytics.sentry.Sentry(pid=os.getpid())
        wandb_sentry.configure_scope(tags={"entity": "tag"})

        wandb_sentry_event_id = wandb_sentry.message(
            expected_wandb_sentry_responses[0].message
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
            expected_other_sentry_response.message  # type: ignore
        )
        wandb_sentry_event_id2 = wandb_sentry.message(
            expected_wandb_sentry_responses[1].message
        )

        relay.wait_for_events(
            [other_sentry_event_id, wandb_sentry_event_id, wandb_sentry_event_id2]
        )

        wandb_sentry_response = relay.events[wandb_sentry_event_id]
        wandb_sentry_response2 = relay.events[wandb_sentry_event_id2]
        other_sentry_envelope = relay.events[other_sentry_event_id]

        # Assert no data is leaked between wandb and other sentry clients
        assert wandb_sentry_response != other_sentry_envelope
        assert wandb_sentry_response2 != other_sentry_envelope

        # Assert expected data is sent to sentry
        assert wandb_sentry_response == expected_wandb_sentry_responses[0]
        assert wandb_sentry_response2 == expected_wandb_sentry_responses[1]
        assert other_sentry_envelope == expected_other_sentry_response


def test_wandb_sentry_exception(relay: MetricRelayServer):
    """
    This test ensures proper isolation between the Sentry instances initialized by another client and by wandb's client.
    In the event that a client sends an exception event to Sentry.

    This test initializes the Sentry client first using `sentry_sdk.init()`, followed by initializing wandb's Sentry client.
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
        tags={
            "entity": "tag",
            "python_runtime": "python",
        },
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
        wandb_sentry = wandb.analytics.sentry.Sentry(pid=os.getpid())

        # Send sentry events
        sentry_sdk.set_tag("test", "tag")
        wandb_sentry.configure_scope(tags={"entity": "tag"})

        other_sentry_event_id = None
        wandb_sentry_event_id = None

        # Raise and capture real exceptions so we have a stack trace in the event.
        try:
            raise Exception(expected_other_sentry_response.message)  # noqa: TRY301
        except Exception as e:
            other_sentry_event_id = sentry_sdk.capture_exception(e)
        try:
            raise Exception(expected_wandb_sentry_response.message)  # noqa: TRY301
        except Exception as e:
            wandb_sentry_event_id = wandb_sentry.exception(e)

        relay.wait_for_events([other_sentry_event_id, wandb_sentry_event_id])

        wandb_sentry_response = relay.events[wandb_sentry_event_id]
        other_sentry_envelope = relay.events[other_sentry_event_id]

        # Assert no data is leaked between wandb and other sentry clients
        assert wandb_sentry_response != other_sentry_envelope

        # Assert expected data is sent to sentry
        assert wandb_sentry_response.stacktrace is not None
        assert other_sentry_envelope == expected_other_sentry_response
        assert wandb_sentry_response == expected_wandb_sentry_response
        assert __file__.endswith(
            wandb_sentry_response.stacktrace["frames"][0]["filename"]
        )
        assert (
            wandb_sentry_response.stacktrace["frames"][0]["function"]
            == "test_wandb_sentry_exception"
        )


def test_repeated_messages_does_not_call_sentry(relay: MetricRelayServer):
    """
    This test verifies that the wandb Sentry client does not send repeated messages to Sentry.
    This test expects that a single event is sent to Sentry when the same message is sent multiple times and is not allowed to be repeated.
    """
    expected_wandb_sentry_response = SentryResponse(
        message="wandb sentry message",
        project_id="123456",
        public_key="WANDB_SENTRY_PUBLIC_KEY",
        tags={
            "entity": "tag",
            "python_runtime": "python",
        },
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
        wandb_sentry = wandb.analytics.sentry.Sentry(pid=os.getpid())
        wandb_sentry.configure_scope(tags={"entity": "tag"})

        # Send sentry events
        wandb_sentry_event_id_1 = wandb_sentry.message(
            expected_wandb_sentry_response.message,
            repeat=False,
        )
        wandb_sentry_event_id_2 = wandb_sentry.message(
            expected_wandb_sentry_response.message,
            repeat=False,
        )
        relay.wait_for_events([wandb_sentry_event_id_1])
        wandb_sentry_response = relay.events[wandb_sentry_event_id_1]

        # Assert first event is sent to Sentry.
        assert wandb_sentry_event_id_1 is not None
        assert wandb_sentry_response == expected_wandb_sentry_response

        # Assert second event is not sent to Sentry.
        assert wandb_sentry_event_id_2 is None


def test_wandb_configure_without_tags_does_not_create_session(relay: MetricRelayServer):
    """
    This test verifies the configuration behavior of the wandb Sentry client.
    It expects the wandb Sentry client does not create a session when no tags are present.
    """
    with mock.patch.dict(
        os.environ,
        {
            wandb.env.ERROR_REPORTING: "true",
            wandb.env.SENTRY_DSN: SENTRY_DSN_FORMAT.format(
                key="WANDB_SENTRY_PUBLIC_KEY",
                port=relay.port,
                project="123456",
            ),
        },
    ):
        wandb_sentry = wandb.analytics.sentry.Sentry(pid=os.getpid())
        wandb_sentry.configure_scope()

        # Assert session is not created when no tags are provided
        assert wandb_sentry.scope._session is None  # type: ignore


def test_wandb_configure_with_tags_creates_session(relay: MetricRelayServer):
    """
    This test verifies the configuration behavior of the wandb Sentry client.
    It expects the wandb Sentry client to create a session when tags are provided.
    It also expects that the session should be None when the session is closed.
    """
    with mock.patch.dict(
        os.environ,
        {
            wandb.env.ERROR_REPORTING: "true",
            wandb.env.SENTRY_DSN: SENTRY_DSN_FORMAT.format(
                key="WANDB_SENTRY_PUBLIC_KEY",
                port=relay.port,
                project="123456",
            ),
        },
    ):
        wandb_sentry = wandb.analytics.sentry.Sentry(pid=os.getpid())
        wandb_sentry.configure_scope(tags={"entity": "tag"})

        # Assert session is created
        assert wandb_sentry.scope is not None
        assert wandb_sentry.scope._session is not None

        # Assert session is removed when ending the session
        wandb_sentry.end_session()
        assert wandb_sentry.scope._session is None


def test_wandb_sentry_event_with_runtime_tags(relay: MetricRelayServer):
    """
    This test verifies that runtime tags are added to the wandb Sentry scope.
    These tags should be present in the event received by Sentry.
    """
    python_runtime = ["colab", "jupyter", "ipython"]

    with mock.patch.dict(
        os.environ,
        {
            wandb.env.ERROR_REPORTING: "true",
            wandb.env.SENTRY_DSN: SENTRY_DSN_FORMAT.format(
                key="WANDB_SENTRY_PUBLIC_KEY",
                port=relay.port,
                project="123456",
            ),
        },
    ):
        wandb_sentry = wandb.analytics.sentry.Sentry(pid=os.getpid())

        for runtime in python_runtime:
            wandb_sentry.configure_scope(
                tags={
                    f"_{runtime}": runtime,
                },
                process_context="context",
            )
            wandb_sentry_event_id = wandb_sentry.message("wandb sentry message")
            relay.wait_for_events([wandb_sentry_event_id])
            wandb_sentry_response = relay.events[wandb_sentry_event_id]

            # Assert runtime tags are present in the Sentry event
            assert wandb_sentry_response.tags["python_runtime"] == runtime
