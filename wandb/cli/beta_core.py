"""Implements `wandb beta core` helpers.

These helpers manage a detached `wandb-core` process intended to be reused by
multiple independent Python processes on the same host.

Discovery is explicit via the WANDB_SERVICE environment variable.
"""

from __future__ import annotations

import logging
import os
from typing import Final, Literal, cast, get_args

import click

from wandb import env as wandb_env
from wandb.analytics import get_sentry
from wandb.proto import wandb_server_pb2 as spb
from wandb.sdk.lib import asyncio_manager
from wandb.sdk.lib.service import service_process, service_token
from wandb.sdk.wandb_settings import Settings

_logger = logging.getLogger(__name__)

Shell = Literal["posix", "fish", "powershell", "cmd"]
SHELL_CHOICES: Final[tuple[str, ...]] = cast(tuple[str, ...], get_args(Shell))


def _format_env_assignment(*, shell: Shell, token_value: str) -> str:
    """Format a shell snippet that sets WANDB_SERVICE.

    Note: WANDB_SERVICE tokens are restricted to alphanumerics, dashes, and a
    system path, so POSIX/fish output does not require quoting/escaping.
    PowerShell requires quoting because '-' would otherwise be parsed as an
    operator.
    """
    if shell == "posix":
        return f"export {wandb_env.SERVICE}={token_value}"
    if shell == "fish":
        return f"set -gx {wandb_env.SERVICE} {token_value};"
    if shell == "powershell":
        return f"$env:{wandb_env.SERVICE} = '{token_value}'"
    if shell == "cmd":
        return f'set "{wandb_env.SERVICE}={token_value}"'

    raise AssertionError(f"Unhandled shell: {shell!r}")


def _format_env_unset(*, shell: Shell) -> str:
    if shell == "posix":
        return f"unset {wandb_env.SERVICE}"
    if shell == "fish":
        return f"set -e {wandb_env.SERVICE};"
    if shell == "powershell":
        return f"Remove-Item Env:{wandb_env.SERVICE} -ErrorAction SilentlyContinue"
    if shell == "cmd":
        # cmd.exe has no true 'unset'; setting to empty is the usual approach.
        return f'set "{wandb_env.SERVICE}="'
    raise AssertionError(f"unhandled shell: {shell!r}")


def start(
    *,
    idle_timeout_seconds: int,
    print_only: bool,
    shell: Shell,
) -> None:
    """Start a detached wandb-core service.

    Args:
        idle_timeout_seconds: If > 0, the service will shut down after this many
            seconds with no connected clients. 0 disables the idle shutdown.
        print_only: If True, print only a shell snippet to set WANDB_SERVICE.
        shell: Which shell syntax to use for the printed snippet.
    """
    get_sentry().configure_scope(process_context="beta-core-start")

    if idle_timeout_seconds < 0:
        raise click.UsageError("--idle-timeout-seconds must be >= 0")

    try:
        token = service_token.from_env()
    except ValueError as e:
        raise click.UsageError(str(e)) from e

    if token:
        raise click.UsageError(
            f"{wandb_env.SERVICE} is already set.\n\n"
            "Run `wandb beta core stop` and/or unset the printed env var.\n"
            "For example (POSIX):\n"
            f'  eval "$(wandb beta core stop --print)"\n'
        )

    proc = service_process.start_detached(
        Settings(),
        idle_timeout_seconds=idle_timeout_seconds,
    )
    proc.token.save_to_env()
    token_value = os.environ[wandb_env.SERVICE]

    assignment = _format_env_assignment(shell=shell, token_value=token_value)

    if print_only:
        click.echo(assignment)
        return

    click.secho("Started detached wandb-core service.", fg="green")

    if idle_timeout_seconds > 0:
        click.echo(f"Idle shutdown: {idle_timeout_seconds}s (service exits when idle).")
    else:
        click.echo("Idle shutdown: disabled (service runs until stopped).")

    click.echo("\nTo use this service in your current shell:")
    click.echo(f"  {assignment}")

    click.echo(
        "\nAny Python process started from that environment will connect to the "
        "existing service instead of spawning its own."
    )


def stop(
    *,
    exit_code: int = 0,
    print_only: bool = False,
    shell: Shell = "posix",
) -> None:
    """Stop a detached wandb-core service addressed by WANDB_SERVICE."""
    get_sentry().configure_scope(process_context="beta-core-stop")

    try:
        token = service_token.from_env()
    except ValueError as e:
        raise click.UsageError(str(e)) from e

    if not token:
        raise click.UsageError(
            f"{wandb_env.SERVICE} is not set.\n\n"
            "Run `wandb beta core start` and set the printed env var.\n"
            "For example (POSIX):\n"
            f'  eval "$(wandb beta core start --print)"\n'
        )

    unset_cmd = _format_env_unset(shell=shell)

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
            "\nTo remove WANDB_SERVICE from your current shell:"
            f"\n  {unset_cmd}"
        ) from e

    except Exception as e:
        get_sentry().reraise(e)

    finally:
        asyncer.join()

    # Clear in this process for programmatic use.
    service_token.clear_service_in_env()

    if print_only:
        click.echo(unset_cmd)
        return

    click.secho("Sent shutdown request to wandb-core.", fg="green")
    click.echo("\nTo remove WANDB_SERVICE from your current shell:")
    click.echo(f"  {unset_cmd}")
