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
@click.option(
    "--include-unsynced",
    help="Delete unsynced run directories as well.",
    is_flag=True,
    default=False,
)
@click.option(
    "--force",
    help="Skip the confirmation prompt.",
    is_flag=True,
    default=False,
)
def clean(
    ctx: click.Context,
    min_hours: int,
    include_unsynced: bool,
    force: bool,
) -> None:
    """Remove synced run data.

    Cleans up the wandb folder, as determined by settings. Usually, this is
    the "wandb" or ".wandb" folder in the current working directory, or
    in the directory specified by the WANDB_DIR environment variable if that
    is set.

    By default, this removes all runs created more than 24 hours ago (based
    on the timestamp in the run folder name) that are online runs or that
    were synced with `wandb sync`.
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
            term.termerror(f"Not a directory: {wandb_dir.as_posix()!r}")
            ctx.exit(1)
    except PermissionError:
        term.termerror(f"Permission error accessing {wandb_dir.as_posix()!r}")
        ctx.exit(1)

    result = _select_runs_to_clean(
        wandb_dir,
        include_unsynced=include_unsynced,
        min_hours=min_hours,
    )

    if result.skipped_too_new:
        term.termlog(
            f"Skipping {result.skipped_too_new} run(s) created fewer than"
            + f" {min_hours} hours ago.",
        )
    if result.skipped_unsynced:
        term.termlog(f"Skipping {result.skipped_unsynced} unsynced run(s).")

    if not result.runs_to_clean:
        term.termlog("Found no runs to clean up.")
        ctx.exit(0)

    result.print_selected_runs()
    if not force and not result.ask_for_confirmation():
        ctx.exit(1)

    exit_code = 0
    for path in result.runs_to_clean:
        try:
            shutil.rmtree(path)
        except OSError as e:
            errstr = f": {e.strerror}" if e.strerror else ""
            term.termerror(f"Failed to remove {path.as_posix()!r}{errstr}")
            exit_code = 1

    if exit_code == 0:
        term.termlog("Success.")
    else:
        term.termwarn("Some runs may not have been removed.")

    ctx.exit(exit_code)


@dataclasses.dataclass()
class _WandbDirResult:
    """A description of the contents of the wandb folder."""

    runs_to_clean: list[pathlib.Path]
    """Runs selected for deletion based on the command options."""

    unsynced: set[pathlib.Path]
    """Selected runs that are unsynced."""

    skipped_too_new: int = 0
    """Count of runs that are filtered out due to age."""

    skipped_unsynced: int = 0
    """Count of runs skipped due not having been synced."""

    def print_selected_runs(self) -> None:
        """Print runs selected for deletion, one per line."""
        term.termlog(f"Found {len(self.runs_to_clean)} run(s) to clean.")
        for path in self.runs_to_clean:
            if path in self.unsynced:
                unsynced_tag = click.style("[unsynced]", fg="red")
                term.termlog(f"  {unsynced_tag} {path.as_posix()}")
            else:
                term.termlog(f"  {path.as_posix()}")

    def ask_for_confirmation(self) -> bool:
        """Prompt for confirmation before deleting runs.

        Returns:
            True if the user wants to proceed, False otherwise.
        """
        unsynced_count = len(self.unsynced)
        if unsynced_count == 0:
            unsynced_msg = ""
        elif unsynced_count == 1:
            unsynced_msg = ", 1 of which is unsynced"
        else:
            unsynced_msg = f", {unsynced_count} of which are unsynced"

        return term.confirm(
            "Are you sure you want to remove"
            + f" {len(self.runs_to_clean)} run(s){unsynced_msg}?",
        )


def _select_runs_to_clean(
    wandb_dir: pathlib.Path,
    *,
    include_unsynced: bool,
    min_hours: int,
) -> _WandbDirResult:
    """Check the wandb folder for runs to clean.

    Args:
        wandb_dir: The path to the wandb folder to examine.
        include_unsynced: If false, skip unsynced runs; else don't.
        min_hours: Minimum age in hours.
    """
    result = _WandbDirResult(runs_to_clean=[], unsynced=set())
    now = _DATETIME_NOW()

    for online_run in wandb_dir.glob("run-*"):
        if not online_run.is_dir():
            term.termwarn(f"Not a directory: {online_run}")
            continue

        if (age := _run_age_hours(now, online_run.name)) and age < min_hours:
            result.skipped_too_new += 1
            continue

        result.runs_to_clean.append(online_run)

    for offline_run in wandb_dir.glob("offline-run-*"):
        if not offline_run.is_dir():
            term.termwarn(f"Not a directory: {offline_run}")
            continue

        is_synced = len(list(offline_run.glob("*.wandb.synced"))) == 1
        if not is_synced and not include_unsynced:
            result.skipped_unsynced += 1
            continue

        if (age := _run_age_hours(now, offline_run.name)) and age < min_hours:
            result.skipped_too_new += 1
            continue

        if not is_synced:
            result.unsynced.add(offline_run)
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
