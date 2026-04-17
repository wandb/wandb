from __future__ import annotations

import json
from datetime import datetime

import click
from cwsandbox.cli.shell import _validate_cmd as _cwsandbox_validate_cmd

from wandb.sandbox import CWSandboxError, Sandbox, SandboxStatus
from wandb.sandbox._auth import _override_sandbox_entity

_STATUS_CHOICES = [s.value for s in SandboxStatus if s != SandboxStatus.UNSPECIFIED]


class SandboxCommand(click.Command):
    """Click command that injects sandbox entity override and error handling."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.params = [
            click.Option(
                ["-e", "--entity"],
                default=None,
                help="Set the W&B entity for sandbox. Default is user's default entity.",
            ),
            *self.params,
        ]

    def invoke(self, ctx: click.Context) -> object:
        entity = ctx.params.pop("entity", None)

        try:
            with _override_sandbox_entity(entity=entity):
                return super().invoke(ctx)
        except CWSandboxError as exc:
            raise click.ClickException(str(exc)) from None


class SandboxGroup(click.Group):
    """Click group for sandbox commands."""

    command_class = SandboxCommand


@click.group(cls=SandboxGroup)
def sandbox() -> None:
    """Manage W&B sandboxes.

    Commands use your default W&B entity unless you pass ``--entity``.
    If a sandbox is not found or you get an auth error, it may have been
    created under a non-default W&B entity. Retry with ``--entity <entity>``.

    Examples:
        # List all pending/running sandboxes
        wandb beta sandbox ls

        # List all sandboxes
        wandb beta sandbox ls -a

        # List sandbox created using non default entity
        wandb beta sandbox ls --entity my-other-team

        # Run single command inside a running sandbox
        wandb beta sandbox exec <sandbox-id> echo hello

        # Open interavtive shell
        wandb beta sandbox sh <sandbox-id>

        # Tail log
        wandb beta sandbox logs <sandbox-id> --follow
    """


@sandbox.command("ls")
@click.option(
    "--status",
    "-s",
    default=None,
    type=click.Choice(_STATUS_CHOICES, case_sensitive=False),
    help="Filter by status.",
)
@click.option(
    "--all",
    "-a",
    "include_stopped",
    is_flag=True,
    default=False,
    help="Include stopped sandboxes in results.",
)
# TODO: cwsandbox is NOT returning the tags in the response object, so we can filter
# by tags, but we cannot show what tags the matched sandbox has ....
@click.option("--tag", "-t", "tags", multiple=True, help="Filter by tag (repeatable).")
@click.option(
    "--output",
    "-o",
    "output_format",
    default="table",
    type=click.Choice(["table", "json"], case_sensitive=False),
    help="Output format.",
)
def list_sandboxes(
    status: str | None,
    include_stopped: bool,
    tags: tuple[str, ...],
    output_format: str,
) -> None:
    """List sandboxes.

    Examples:
        # List all non stopped
        wandb beta sandbox ls

        wandb beta sandbox ls -a

        wandb beta sandbox ls --status running

        wandb beta sandbox ls --tag foo --output json

        wandb beta sandbox ls --entity team
    """
    sandboxes = Sandbox.list(
        tags=list(tags) if tags else None,
        status=status,
        include_stopped=include_stopped,
    ).result()

    if output_format == "json":
        data = [
            {
                "sandbox_id": sb.sandbox_id,
                "status": sb.status.value if sb.status else None,
                "started_at": sb.started_at.isoformat() if sb.started_at else None,
            }
            for sb in sandboxes
        ]
        click.echo(json.dumps(data, indent=2))
        return

    if not sandboxes:
        click.echo("No sandboxes found.")
        return

    click.echo(f"{'SANDBOX ID':<40} {'STATUS':<14} {'STARTED AT'}")
    click.echo(f"{'-' * 40} {'-' * 14} {'-' * 24}")

    for sb in sandboxes:
        sid = sb.sandbox_id or "-"
        st = sb.status.value if sb.status else "-"
        started = (
            sb.started_at.strftime("%Y-%m-%d %H:%M:%S UTC") if sb.started_at else "-"
        )
        click.echo(f"{sid:<40} {st:<14} {started}")


@sandbox.command("sh")
@click.argument("sandbox_id")
@click.option(
    "--cmd",
    default="/bin/bash",
    callback=_cwsandbox_validate_cmd,
    help="Command to run (default: /bin/bash). Accepts full command strings.",
)
def shell(
    sandbox_id: str,
    cmd: str,
) -> None:
    """Open an interactive shell in a sandbox.

    SANDBOX_ID is the ID of the sandbox to connect to.

    Examples:
        wandb beta sandbox sh <sandbox-id>

        wandb beta sandbox sh <sandbox-id> --cmd /bin/zsh

        wandb beta sandbox sh --entity team <sandbox-id>
    """
    from cwsandbox.cli.shell import shell

    callback = shell.callback
    if callback is None:
        raise click.ClickException("Failed to load the cwsandbox CLI command.")

    callback(sandbox_id=sandbox_id, cmd=cmd)


@sandbox.command(
    "exec",
    context_settings={"ignore_unknown_options": True},
)
@click.argument("sandbox_id")
@click.argument("command_args", nargs=-1, required=True, type=click.UNPROCESSED)
@click.option(
    "--cwd",
    "-w",
    default=None,
    help="Working directory for the command.",
)
@click.option(
    "--timeout",
    "-t",
    "timeout_seconds",
    type=click.FloatRange(min=0, min_open=True),
    default=None,
    help="Timeout in seconds.",
)
def exec_in_sandbox(
    sandbox_id: str,
    command_args: tuple[str, ...],
    cwd: str | None,
    timeout_seconds: float | None,
) -> None:
    """Execute a command in a sandbox.

    SANDBOX_ID is the ID of the sandbox to run the command in.

    Examples:
        wandb beta sandbox exec <sandbox-id> echo hello

        wandb beta sandbox exec <sandbox-id> python -c "print('ok')"

        wandb beta sandbox exec <sandbox-id> --cwd /app python app.py

        wandb beta sandbox exec --entity team <sandbox-id> echo hello
    """
    from cwsandbox.cli.exec import exec_command

    callback = exec_command.callback
    if callback is None:
        raise click.ClickException("Failed to load the cwsandbox exec command.")

    callback(
        sandbox_id=sandbox_id,
        command=command_args,
        cwd=cwd,
        timeout_seconds=timeout_seconds,
    )


@sandbox.command("logs")
@click.argument("sandbox_id")
@click.option(
    "--follow",
    "-f",
    is_flag=True,
    default=False,
    help="Follow log output (like tail -f).",
)
@click.option(
    "--tail",
    "tail_lines",
    type=click.IntRange(min=0),
    default=None,
    help="Number of recent lines to show.",
)
@click.option(
    "--since",
    "since_time",
    type=click.DateTime(),
    default=None,
    help="Show logs since timestamp (e.g. 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM:SS').",
)
@click.option(
    "--timestamps", "-t", is_flag=True, default=False, help="Show timestamps."
)
def logs(
    sandbox_id: str,
    follow: bool,
    tail_lines: int | None,
    since_time: datetime | None,
    timestamps: bool,
) -> None:
    """Stream logs from a sandbox's main process.

    Streams stdout/stderr from the command used to create the sandbox. Output
    from ``wandb beta sandbox exec`` commands is not included.

    SANDBOX_ID is the ID of the sandbox to stream logs from.

    Examples:
        wandb beta sandbox logs <sandbox-id>

        wandb beta sandbox logs <sandbox-id> --tail 50

        wandb beta sandbox logs <sandbox-id> --follow --timestamps

        wandb beta sandbox logs --entity team <sandbox-id>
    """
    from cwsandbox.cli.logs import logs

    callback = logs.callback
    if callback is None:
        raise click.ClickException("Failed to load the cwsandbox logs command.")

    callback(
        sandbox_id=sandbox_id,
        follow=follow,
        tail_lines=tail_lines,
        since_time=since_time,
        timestamps=timestamps,
    )
