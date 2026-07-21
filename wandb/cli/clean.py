"""Implements `wandb clean`."""

from __future__ import annotations

import dataclasses
import pathlib
import shutil

import click

from wandb.errors import term
from wandb.sdk import wandb_setup


@click.command()
@click.pass_context
def clean(ctx: click.Context) -> None:
    """Remove synced run data.

    Cleans up the wandb folder, as determined by settings. Usually, this is
    the "wandb" or ".wandb" folder in the current working directory, or
    in the directory specified by the WANDB_DIR environment variable if that
    is set.

    This removes all online runs and any offline runs that have been synced
    with `wandb sync`.
    """
    settings = wandb_setup.singleton().settings
    wandb_dir = pathlib.Path(settings.wandb_dir)

    # Prefer to print paths relative to the current working directory.
    cwd = pathlib.Path.cwd()
    if wandb_dir.is_relative_to(cwd):
        wandb_dir = wandb_dir.relative_to(cwd)

    # Check that the wandb directory is correctly configured.
    try:
        if not wandb_dir.exists():
            term.termerror("No wandb directory found.")
            ctx.exit(1)
        if not wandb_dir.is_dir():
            term.termerror(f"Not a directory: {str(wandb_dir)!r}")
            ctx.exit(1)
    except PermissionError:
        term.termerror(f"Permission error accessing {str(wandb_dir)!r}")
        ctx.exit(1)

    result = _examine_wandb_directory(wandb_dir)

    if not result.synced_runs:
        term.termlog(f"Found no synced runs, {result.unsynced} unsynced.")
        ctx.exit(0)

    term.termlog(f"Found {len(result.synced_runs)} synced run(s).")
    for path in result.synced_runs:
        term.termlog(f"  {path}")
    if not term.confirm(
        f"Are you sure you want to remove {len(result.synced_runs)} run(s)?",
    ):
        ctx.exit(1)

    exit_code = 0
    for path in result.synced_runs:
        try:
            shutil.rmtree(path)
        except OSError as e:
            errstr = f": {e.strerror}" if e.strerror else ""
            term.termerror(f"Failed to remove {str(path)!r}{errstr}")
            exit_code = 1

    ctx.exit(exit_code)


@dataclasses.dataclass()
class _WandbDirResult:
    """A description of the contents of the wandb folder."""

    synced_runs: list[pathlib.Path]
    """Folders of online or synced runs."""

    unsynced: int = 0
    """Count of unsynced runs."""


def _examine_wandb_directory(wandb_dir: pathlib.Path) -> _WandbDirResult:
    """Check the wandb folder for runs to clean.

    Args:
        wandb_dir: The path to the wandb folder to examine.
    """
    result = _WandbDirResult(synced_runs=[])

    for online_run in wandb_dir.glob("run-*"):
        if not online_run.is_dir():
            term.termwarn(f"Not a directory: {online_run}")
            continue

        result.synced_runs.append(online_run)

    for offline_run in wandb_dir.glob("offline-run-*"):
        if not offline_run.is_dir():
            term.termwarn(f"Not a directory: {offline_run}")
            continue

        synced_marker_count = len(list(offline_run.glob("*.wandb.synced")))
        if synced_marker_count != 1:
            result.unsynced += 1
            continue  # Not synced yet, or invalid if >1 marker file.

        result.synced_runs.append(offline_run)

    return result
