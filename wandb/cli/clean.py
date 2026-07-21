"""Implements `wandb clean`."""

from __future__ import annotations

import dataclasses
import pathlib
import re
import shutil
from datetime import datetime

import click

from wandb.errors import term
from wandb.sdk import wandb_setup

# Patched in tests.
_DATETIME_NOW = datetime.now


@click.command()
@click.pass_context
@click.option(
    "--min-hours",
    help="Minimum run age in hours for deletion (default 24).",
    default=24,
)
def clean(ctx: click.Context, min_hours: int) -> None:
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

    result = _examine_wandb_directory(wandb_dir, min_hours=min_hours)

    if result.too_young:
        term.termlog(
            f"Skipping {result.too_young} run(s) created fewer than"
            + f" {min_hours} hours ago.",
        )
    if result.unsynced:
        term.termlog(f"Skipping {result.unsynced} unsynced run(s).")
    if not result.runs_to_clean:
        term.termlog("Found no runs to clean up.")
        ctx.exit(0)

    term.termlog(f"Found {len(result.runs_to_clean)} synced run(s).")
    for path in result.runs_to_clean:
        term.termlog(f"  {path}")
    if not term.confirm(
        f"Are you sure you want to remove {len(result.runs_to_clean)} run(s)?",
    ):
        ctx.exit(1)

    exit_code = 0
    for path in result.runs_to_clean:
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

    runs_to_clean: list[pathlib.Path]
    """Folders of online or synced runs that are old enough for deletion."""

    too_young: int = 0
    """Count of synced runs that are filtered out due to age."""

    unsynced: int = 0
    """Count of unsynced runs."""


def _examine_wandb_directory(
    wandb_dir: pathlib.Path,
    *,
    min_hours: int,
) -> _WandbDirResult:
    """Check the wandb folder for runs to clean.

    Args:
        wandb_dir: The path to the wandb folder to examine.
        min_hours: Minimum age in hours.
    """
    result = _WandbDirResult(runs_to_clean=[])
    now = _DATETIME_NOW()

    for online_run in wandb_dir.glob("run-*"):
        if not online_run.is_dir():
            term.termwarn(f"Not a directory: {online_run}")
            continue

        if (age := _run_age_hours(now, online_run.name)) and age < min_hours:
            result.too_young += 1
            continue

        result.runs_to_clean.append(online_run)

    for offline_run in wandb_dir.glob("offline-run-*"):
        if not offline_run.is_dir():
            term.termwarn(f"Not a directory: {offline_run}")
            continue

        synced_marker_count = len(list(offline_run.glob("*.wandb.synced")))
        if synced_marker_count != 1:
            result.unsynced += 1
            continue  # Not synced yet, or invalid if >1 marker file.

        if (age := _run_age_hours(now, offline_run.name)) and age < min_hours:
            result.too_young += 1
            continue

        result.runs_to_clean.append(offline_run)

    return result


def _run_age_hours(now: datetime, run_folder_name: str) -> int | None:
    # Required for the subtraction below.
    # strptime with our format returns a naive datetime.
    assert not now.tzinfo, "Requires a naive datetime."

    run_timestamp_re = re.compile(r"\d{8}_\d{6}")
    match = run_timestamp_re.search(run_folder_name)
    if not match:
        return None

    try:
        run_datetime = datetime.strptime(match.group(0), "%Y%m%d_%H%M%S")
    except ValueError:
        return None

    time_delta = now - run_datetime
    return int(time_delta.total_seconds() / 3600)
