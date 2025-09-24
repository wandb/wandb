"""Beta versions of wandb CLI commands.

These commands are experimental and may change or be removed in future versions.
"""

from __future__ import annotations

import os
import pathlib

import click

import wandb
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


@beta.command(
    name="leet",
    help=(
        "Lightweight Experiment Exploration Tool.\n\n"
        "A terminal UI for viewing your W&B runs locally.\n\n"
        "If no directory is specified, wandb-leet will look for "
        "the latest-run symlink in ./wandb or ./.wandb"
    ),
)
@click.pass_context
@click.argument("wandb_dir", nargs=1, type=click.Path(exists=True), required=False)
def leet(ctx, wandb_dir: str = None):
    """Launch the wandb-leet terminal UI.

    Args:
        ctx: Click context
        wandb_dir: Optional path to a W&B run directory containing a .wandb file.
                   If not provided, looks for latest-run symlink in ./wandb or ./.wandb
    """
    wandb._sentry.configure_scope(process_context="leet")

    try:
        core_path = get_core_path()

        args = [core_path, "leet"]
        if wandb_dir:
            args.append(wandb_dir)

        os.execvp(core_path, args)
    except Exception as e:
        wandb._sentry.reraise(e)


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
