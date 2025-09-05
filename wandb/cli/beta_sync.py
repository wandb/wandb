"""Implements `wandb sync` using wandb-core."""

from __future__ import annotations

import asyncio
import pathlib
import time
from itertools import filterfalse
from typing import Iterable, Iterator

import click

import wandb
from wandb.proto.wandb_sync_pb2 import ServerSyncResponse
from wandb.sdk import wandb_setup
from wandb.sdk.lib import asyncio_compat
from wandb.sdk.lib.printer import ERROR, Printer, new_printer
from wandb.sdk.lib.progress import progress_printer
from wandb.sdk.lib.service.service_connection import ServiceConnection
from wandb.sdk.mailbox.mailbox_handle import MailboxHandle

_MAX_LIST_LINES = 20
_POLL_WAIT_SECONDS = 0.1
_SLEEP = asyncio.sleep  # patched in tests


def sync(
    paths: list[pathlib.Path],
    *,
    dry_run: bool,
    skip_synced: bool,
) -> None:
    """Replay one or more .wandb files.

    Args:
        paths: One or more .wandb files, run directories containing
            .wandb files, and wandb directories containing run directories.
        dry_run: If true, just prints what it would do and exits.
        skip_synced: If true, skips files that have already been synced
            as indicated by a .wandb.synced marker file in the same directory.
    """
    wandb_files: set[pathlib.Path] = set()
    for path in paths:
        for wandb_file in _find_wandb_files(path, skip_synced=skip_synced):
            wandb_files.add(wandb_file.resolve())

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
    singleton.asyncer.run(
        lambda: _do_sync(
            wandb_files,
            service=service,
            settings=singleton.settings,
            printer=printer,
        )
    )


async def _do_sync(
    wandb_files: set[pathlib.Path],
    *,
    service: ServiceConnection,
    settings: wandb.Settings,
    printer: Printer,
) -> None:
    """Sync the specified files.

    This is factored out to make the progress animation testable.
    """
    init_result = await service.init_sync(
        wandb_files,
        settings,
    ).wait_async(timeout=5)

    sync_handle = service.sync(init_result.id)

    await _SyncStatusLoop(
        init_result.id,
        service,
        printer,
    ).wait_with_progress(sync_handle)


class _SyncStatusLoop:
    """Displays a sync operation's status until it completes."""

    def __init__(
        self,
        id: str,
        service: ServiceConnection,
        printer: Printer,
    ) -> None:
        self._id = id
        self._service = service
        self._printer = printer

        self._rate_limit_last_time: float | None = None
        self._done = asyncio.Event()

    async def wait_with_progress(
        self,
        handle: MailboxHandle[ServerSyncResponse],
    ) -> None:
        """Display status updates until the handle completes."""
        async with asyncio_compat.open_task_group() as group:
            group.start_soon(self._wait_then_mark_done(handle))
            group.start_soon(self._show_progress_until_done())

    async def _wait_then_mark_done(
        self,
        handle: MailboxHandle[ServerSyncResponse],
    ) -> None:
        response = await handle.wait_async(timeout=None)
        if messages := list(response.errors):
            self._printer.display(messages, level=ERROR)
        self._done.set()

    async def _show_progress_until_done(self) -> None:
        """Show rate-limited status updates until _done is set."""
        with progress_printer(self._printer, "Syncing...") as progress:
            while not await self._rate_limit_check_done():
                handle = self._service.sync_status(self._id)
                response = await handle.wait_async(timeout=None)

                if messages := list(response.new_errors):
                    self._printer.display(messages, level=ERROR)
                progress.update(response.stats)

    async def _rate_limit_check_done(self) -> bool:
        """Wait for rate limit and return whether _done is set."""
        now = time.monotonic()
        last_time = self._rate_limit_last_time
        self._rate_limit_last_time = now

        if last_time and (time_since_last := now - last_time) < _POLL_WAIT_SECONDS:
            await asyncio_compat.race(
                _SLEEP(_POLL_WAIT_SECONDS - time_since_last),
                self._done.wait(),
            )

        return self._done.is_set()


def _find_wandb_files(
    path: pathlib.Path,
    *,
    skip_synced: bool,
) -> Iterator[pathlib.Path]:
    """Returns paths to the .wandb files to sync."""
    if skip_synced:
        yield from filterfalse(_is_synced, _expand_wandb_files(path))
    else:
        yield from _expand_wandb_files(path)


def _expand_wandb_files(
    path: pathlib.Path,
) -> Iterator[pathlib.Path]:
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
        paths: Paths to print. Must be absolute with symlinks resolved.
    """
    # Prefer to print paths relative to the current working directory.
    cwd = pathlib.Path(".").resolve()
    formatted_paths: list[str] = []
    for path in paths:
        try:
            formatted_path = str(path.relative_to(cwd))
        except ValueError:
            formatted_path = str(path)
        formatted_paths.append(formatted_path)

    sorted_paths = sorted(formatted_paths)

    for i in range(min(len(sorted_paths), _MAX_LIST_LINES)):
        click.echo(f"  {sorted_paths[i]}")

    if len(sorted_paths) > _MAX_LIST_LINES:
        remaining = len(sorted_paths) - _MAX_LIST_LINES
        click.echo(f"  +{remaining:,d} more")
