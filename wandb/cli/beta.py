"""Beta versions of wandb CLI commands.

These commands are experimental and may change or be removed in future versions.
"""

from __future__ import annotations

import pathlib

import click

from wandb.errors import WandbCoreNotAvailableError
from wandb.util import get_core_path


@click.group()
def beta():
    """Beta versions of wandb CLI commands."""
    import wandb.env

    wandb._sentry.configure_scope(process_context="wandb_beta")

    try:
        get_core_path()
    except WandbCoreNotAvailableError as e:
        wandb._sentry.exception(f"using `wandb beta`. failed with {e}")
        click.secho(
            (e),
            fg="red",
            err=True,
        )


@beta.command()
@click.argument("path", nargs=1, type=click.Path(exists=True), required=False)
def leet(path: str | None = None) -> None:
    """Launch W&B LEET: the Lightweight Experiment Exploration Tool.

    LEET is a terminal UI for viewing a W&B run specified by an optional PATH.

    PATH can include a .wandb file or a run directory containing a .wandb file.
    If PATH is not provided, the command will look for the latest run.
    """
    from . import beta_leet

    beta_leet.launch(path)


@beta.command()
@click.argument("paths", type=click.Path(exists=True), nargs=-1)
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
    help="Max number of runs to sync at a time.",
)
def sync(
    paths: tuple[str, ...],
    skip_synced: bool,
    dry_run: bool,
    verbose: bool,
    n: int,
) -> None:
    """Upload .wandb files specified by PATHS.

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
        dry_run=dry_run,
        skip_synced=skip_synced,
        verbose=verbose,
        parallelism=n,
    )
