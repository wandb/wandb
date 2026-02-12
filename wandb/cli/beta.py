"""Beta versions of wandb CLI commands.

These commands are experimental and may change or be removed in future versions.
"""

from __future__ import annotations

import pathlib
from typing import Any

import click

from wandb.analytics import get_sentry
from wandb.errors import WandbCoreNotAvailableError
from wandb.util import get_core_path


class DefaultCommandGroup(click.Group):
    """A click Group that falls through to a default command.

    If the first argument isn't a recognized subcommand, the default
    command is invoked with all arguments passed through. This allows
    backward-compatible CLIs where `cmd [path]` and `cmd run [path]`
    are equivalent.
    """

    def __init__(self, *args: Any, default_cmd: str = "run", **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.default_cmd = default_cmd

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        if not args or args[0].startswith("-") or args[0] not in self.commands:
            args = [self.default_cmd, *args]
        return super().parse_args(ctx, args)

    def format_usage(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        formatter.write_usage(ctx.command_path, "[PATH] | COMMAND [ARGS]...")


@click.group()
def beta() -> None:
    """Beta versions of wandb CLI commands.

    These commands may change or even completely break in any release of wandb.
    """
    get_sentry().configure_scope(process_context="wandb_beta")

    try:
        get_core_path()
    except WandbCoreNotAvailableError as e:
        get_sentry().exception(f"using `wandb beta`. failed with {e}")
        click.secho(
            (e),
            fg="red",
            err=True,
        )


@beta.group(cls=DefaultCommandGroup, default_cmd="run", invoke_without_command=True)
@click.pass_context
def leet(ctx: click.Context) -> None:
    """W&B LEET: the Lightweight Experiment Exploration Tool.

    A terminal UI for viewing your W&B runs locally.

    Examples:
        wandb beta leet                 View latest run
        wandb beta leet ./wandb         View runs in directory
    """
    pass


@leet.command()
@click.argument("path", nargs=1, type=click.STRING, required=False)
@click.option(
    "--pprof",
    default="",
    hidden=True,
    help="Serve /debug/pprof/* on this address (e.g. 127.0.0.1:6060).",
)
def run(path: str | None = None, pprof: str = "") -> None:
    """Launch the LEET TUI.

    PATH can be a .wandb file, a run directory, or a wandb directory.
    If omitted, searches for the latest run.
    """
    from . import beta_leet

    beta_leet.launch(path, pprof)


@leet.command()
def config() -> None:
    """Edit LEET configuration."""
    from . import beta_leet

    beta_leet.launch_config()


@beta.command()
@click.argument("paths", type=click.Path(exists=True), nargs=-1)
@click.option(
    "--live",
    is_flag=True,
    default=False,
    help="""Sync a run while it's still being logged.

    This may hang if the process generating the run crashes uncleanly.
    """,
)
@click.option(
    "-e",
    "--entity",
    default="",
    help="An entity override to use for all runs being synced.",
)
@click.option(
    "-p",
    "--project",
    default="",
    help="A project override to use for all runs being synced.",
)
@click.option(
    "--id",
    "run_id",
    default="",
    help="""A run ID override to use for all runs being synced.

    If setting this and syncing multiple files (with the same entity
    and project), the files will be synced in order of start time.
    This is intended to work with syncing multiple resumed fragments
    of the same run.
    """,
)
@click.option(
    "--job-type",
    default="",
    help="A job type override for all runs being synced.",
)
@click.option(
    "--replace-tags",
    default="",
    help="Rename tags using the format 'old1=new1,old2=new2'.",
)
@click.option(
    "--skip-synced/--no-skip-synced",
    is_flag=True,
    default=True,
    help="Skip runs that have already been synced with this command.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Print what would happen without uploading anything.",
)
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    default=False,
    help="Print more information.",
)
@click.option(
    "-n",
    default=5,
    help="""Max number of runs to sync at a time.

    When syncing multiple files that are part of the same run,
    the files are synced sequentially in order of start time
    regardless of this setting. This happens for resumed runs
    or when using the --id parameter.
    """,
)
def sync(
    paths: tuple[str, ...],
    live: bool,
    entity: str,
    project: str,
    run_id: str,
    job_type: str,
    replace_tags: str,
    skip_synced: bool,
    dry_run: bool,
    verbose: bool,
    n: int,
) -> None:
    """Upload .wandb files specified by PATHS.

    This is a beta re-implementation of `wandb sync`.
    It is not feature complete, not guaranteed to work, and may change
    in backward-incompatible ways in any release of wandb.

    PATHS can include .wandb files, run directories containing .wandb files,
    and "wandb" directories containing run directories.

    For example, to sync all runs in a directory:

        wandb beta sync ./wandb

    To sync a specific run:

        wandb beta sync ./wandb/run-20250813_124246-n67z9ude

    Or equivalently:

        wandb beta sync ./wandb/run-20250813_124246-n67z9ude/run-n67z9ude.wandb
    """
    from . import beta_sync

    beta_sync.sync(
        [pathlib.Path(path) for path in paths],
        live=live,
        entity=entity,
        project=project,
        run_id=run_id,
        job_type=job_type,
        replace_tags=replace_tags,
        dry_run=dry_run,
        skip_synced=skip_synced,
        verbose=verbose,
        parallelism=n,
    )
