"""Beta versions of wandb CLI commands.

These commands are experimental and may change or be removed in future versions.
"""

from __future__ import annotations

import pathlib

import click

from wandb.analytics import get_sentry
from wandb.errors import WandbCoreNotAvailableError
from wandb.util import get_core_path


@click.group()
def beta():
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


@beta.command()
@click.argument("path", nargs=1, type=click.Path(exists=True), required=False)
@click.option(
    "--pprof",
    default="",
    hidden=True,
    help="""Run with pprof enabled at a specified address, e.g. --pprof=127.0.0.1:6060.

    If set, serves /debug/pprof/* on this address, e.g. 127.0.0.1:6060/debug/pprof.
    """,
)
def leet(
    path: str | None = None,
    pprof: str = "",
) -> None:
    """Launch W&B LEET: the Lightweight Experiment Exploration Tool.

    LEET is a terminal UI for viewing a W&B run specified by an optional PATH.

    PATH can include a .wandb file or a run directory containing a .wandb file.
    If PATH is not provided, the command will look for the latest run.
    """
    from . import beta_leet

    beta_leet.launch(path, pprof)


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

    ```shell
    wandb beta sync ./wandb
    ```

    To sync a specific run:

    ```shell
    wandb beta sync ./wandb/run-20250813_124246-n67z9ude
    ```

    Or equivalently:

    ```shell
    wandb beta sync ./wandb/run-20250813_124246-n67z9ude/run-n67z9ude.wandb
    ```
    """
    from . import beta_sync

    beta_sync.sync(
        [pathlib.Path(path) for path in paths],
        live=live,
        entity=entity,
        project=project,
        run_id=run_id,
        dry_run=dry_run,
        skip_synced=skip_synced,
        verbose=verbose,
        parallelism=n,
    )
