"""`wandb beta core` commands.

These commands manage a detached wandb-core instance intended to be shared by
multiple Python processes on the same machine.

The service is discovered explicitly via the WANDB_SERVICE environment
variable; `wandb beta core start` prints an export command that you can apply
in your shell.
"""

from __future__ import annotations

import logging

import click

from wandb.proto import wandb_server_pb2 as spb
from wandb.sdk.lib import asyncio_manager
from wandb.sdk.lib.service import service_process, service_token
from wandb.sdk.wandb_settings import Settings

_logger = logging.getLogger(__name__)


def start(*, idle_timeout_seconds: int) -> None:
    """Start a detached wandb-core service."""
    if idle_timeout_seconds < 0:
        raise click.UsageError("--idle-timeout-seconds must be >= 0")

    settings = Settings()
    proc = service_process.start_detached(
        settings,
        idle_timeout_seconds=idle_timeout_seconds,
    )
    token = proc.token

    click.secho("Started detached wandb-core service.", fg="green")

    if idle_timeout_seconds > 0:
        click.echo(f"Idle shutdown: {idle_timeout_seconds}s (service exits when idle).")
    else:
        click.echo("Idle shutdown: disabled (service runs until stopped).")

    click.echo("\nTo use this service in your current shell:")
    click.echo(f"  export WANDB_SERVICE={token.as_env_string()}")

    click.echo(
        "\nAny Python process started from that environment will connect to the "
        "existing service instead of spawning its own."
    )


def stop(*, exit_code: int) -> None:
    """Stop a detached wandb-core service referenced by WANDB_SERVICE."""
    token = service_token.from_env()
    if not token:
        raise click.UsageError(
            "WANDB_SERVICE is not set. "
            "Run `wandb beta core start` and export the printed WANDB_SERVICE."
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
            f"Failed to connect to wandb-core using WANDB_SERVICE: {e}"
        ) from e

    finally:
        asyncer.join()

    click.secho("Sent shutdown request to wandb-core.", fg="green")
