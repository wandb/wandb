"""Implements `wandb beta core` helpers.

These helpers manage a detached `wandb-core` process intended to be reused by
multiple independent Python processes on the same host.

Discovery is explicit via the WANDB_SERVICE environment variable.
"""

from __future__ import annotations

import logging

import click

from wandb import env as wandb_env
from wandb.analytics import get_sentry
from wandb.proto import wandb_server_pb2 as spb
from wandb.sdk.lib import asyncio_manager
from wandb.sdk.lib.service import service_process, service_token
from wandb.sdk.wandb_settings import Settings

_logger = logging.getLogger(__name__)
DEFAULT_IDLE_TIMEOUT = service_process.DEFAULT_DETACHED_IDLE_TIMEOUT


def start(*, idle_timeout: str) -> None:
    """Start a detached wandb-core service.

    Args:
        idle_timeout: How long the service should stay alive with no connected
            clients before shutting down. This uses Go duration syntax, for
            example ``30s`` or ``10m``. Use ``0`` to disable idle shutdown.
    """
    try:
        token = service_token.from_env()
    except ValueError as e:
        raise click.UsageError(str(e)) from None

    if token:
        raise click.UsageError(
            f"{wandb_env.SERVICE} is already set. Clear it or run "
            "`wandb beta core stop` before starting another detached service."
        )

    proc = service_process.start_detached(Settings(), idle_timeout=idle_timeout)
    token_value = proc.token.env_value

    click.secho("Started detached wandb-core service.", fg="green", err=True)
    click.echo(f"Idle shutdown: {idle_timeout}.", err=True)
    click.echo(
        f"Set {wandb_env.SERVICE} to this value before starting worker processes:",
        err=True,
    )
    click.echo(token_value)  # Print the token to stdout for programmatic use.
    click.echo(
        "Any Python process launched with that environment variable will "
        "connect to the existing service instead of spawning its own.",
        err=True,
    )


def stop(*, exit_code: int = 0) -> None:
    """Stop a detached wandb-core service addressed by WANDB_SERVICE."""
    get_sentry().configure_scope(process_context="beta-core-stop")

    try:
        token = service_token.from_env()
    except ValueError as e:
        raise click.UsageError(str(e)) from None

    if not token:
        raise click.UsageError(
            f"{wandb_env.SERVICE} is not set. Set it to the detached service "
            "you want to stop and rerun the command."
        )

    asyncer = asyncio_manager.AsyncioManager()
    asyncer.start()
    try:
        client = token.connect(asyncer=asyncer)

        async def publish_teardown_and_close() -> None:
            await client.publish(
                spb.ServerRequest(
                    inform_teardown=spb.ServerInformTeardownRequest(exit_code=exit_code)
                )
            )
            await client.close()

        asyncer.run(publish_teardown_and_close)

    except service_token.WandbServiceConnectionError as e:
        _logger.exception("Failed to connect to wandb-core for stop")
        raise click.ClickException(
            f"Failed to connect to wandb-core using {wandb_env.SERVICE}: {e}"
        ) from e

    except Exception as e:
        get_sentry().reraise(e)

    finally:
        asyncer.join()

    service_token.clear_service_in_env()

    click.secho("Sent shutdown request to wandb-core.", fg="green", err=True)
    click.echo(
        f"Clear {wandb_env.SERVICE} from any shells or process environments "
        "that still set it.",
        err=True,
    )
