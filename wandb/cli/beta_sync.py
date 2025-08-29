"""Implements `wandb sync` using wandb-core."""

from __future__ import annotations

import pathlib
from itertools import filterfalse
from typing import Iterable

import click
from typing_extensions import Generator

from wandb.sdk import wandb_setup
from wandb.sdk.lib.printer import ERROR, new_printer

_MAX_LIST_LINES = 20


def sync(
    path: pathlib.Path,
    *,
    dry_run: bool,
    skip_synced: bool,
) -> None:
    """Replay one or more .wandb files.

    Args:
        path: A .wandb file, a run directory containing a .wandb file, or
            a wandb directory containing run directories.
        dry_run: If true, just prints what it would do and exits.
        skip_synced: If true, skips files that have already been synced
            as indicated by a .wandb.synced marker file in the same directory.
    """
    wandb_files = _find_wandb_files(path, skip_synced=skip_synced)

    if not wandb_files:
        click.echo("No files to sync.")
        return

    if dry_run:
        click.echo(f"Would sync {len(wandb_files)} file(s):")
        _print_sorted_paths(wandb_files)
        return

    click.echo(f"Syncing {len(wandb_files)} file(s):")
    _print_sorted_paths(wandb_files)

    singleton = wandb_setup.singleton()
    service = singleton.ensure_service()
    printer = new_printer()

    init_handle = service.init_sync(wandb_files, singleton.settings)
    sync_id = init_handle.wait_or(timeout=5).id
    sync_result = service.sync(sync_id).wait_or(timeout=None)

    if messages := list(sync_result.errors):
        printer.display(messages, level=ERROR)


def _find_wandb_files(
    path: pathlib.Path,
    *,
    skip_synced: bool,
) -> set[pathlib.Path]:
    """Returns paths to the .wandb files to sync."""
    if skip_synced:
        return set(filterfalse(_is_synced, _expand_wandb_files(path)))
    else:
        return set(_expand_wandb_files(path))


def _expand_wandb_files(
    path: pathlib.Path,
) -> Generator[pathlib.Path, None, None]:
    """Iterate over .wandb files selected by the path."""
    if path.suffix == ".wandb":
        yield path
        return

    files_in_run_directory = path.glob("*.wandb")
    try:
        first_file = next(files_in_run_directory)
    except StopIteration:
        pass
    else:
        yield first_file
        yield from files_in_run_directory
        return

    yield from path.glob("*/*.wandb")


def _is_synced(path: pathlib.Path) -> bool:
    """Returns whether the .wandb file is synced."""
    return path.with_suffix(".wandb.synced").exists()


def _print_sorted_paths(paths: Iterable[pathlib.Path]) -> None:
    """Print file paths, sorting them and truncating the list if needed.

    Args:
        paths: Paths to print.
    """
    sorted_paths = sorted(str(path) for path in paths)

    for i in range(min(len(sorted_paths), _MAX_LIST_LINES)):
        click.echo(f"  {sorted_paths[i]}")

    if len(sorted_paths) > _MAX_LIST_LINES:
        remaining = len(sorted_paths) - _MAX_LIST_LINES
        click.echo(f"  +{remaining:,d} more")
