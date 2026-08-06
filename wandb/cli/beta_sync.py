"""Implements `wandb sync` using wandb-core."""

from __future__ import annotations

import asyncio
import contextlib
import pathlib
from collections.abc import Iterable, Iterator

import wandb
from wandb.errors import term
from wandb.proto.wandb_sync_pb2 import ServerSyncResponse
from wandb.sdk import wandb_setup
from wandb.sdk.lib import asyncio_compat, ratelimit, wbauth
from wandb.sdk.lib.printer import Printer, new_printer
from wandb.sdk.lib.progress import progress_printer
from wandb.sdk.lib.service.service_connection import ServiceConnection
from wandb.sdk.mailbox.mailbox_handle import MailboxHandle

_MAX_LIST_LINES = 20
_POLL_WAIT_SECONDS = 0.1


def sync(
    paths: list[pathlib.Path],
    *,
    live: bool,
    entity: str,
    project: str,
    run_id: str,
    job_type: str,
    replace_tags: str,
    dry_run: bool,
    skip_confirmation: bool,
    skip_synced: bool,
    skip_online: bool,
    verbose: bool,
    parallelism: int,
) -> None:
    """Replay one or more .wandb files.

    Args:
        paths: Zero or more .wandb files, run directories containing
            .wandb files, and wandb directories containing run directories.
            If no paths given, uses the wandb_dir setting.
        live: Whether to enable 'live' mode, which indefinitely retries reading
            incomplete transaction logs.
        entity: The entity override for all paths, or an empty string.
        project: The project override for all paths, or an empty string.
        run_id: The run ID override for all paths, or an empty string.
        job_type: An override for the job type for all runs, or an empty string.
        replace_tags: A string in the form 'old1=new1,old2=new2' that defines
            how to rename run tags.
        dry_run: If true, just prints what it would do and exits.
        skip_confirmation: If true, don't ask for confirmation.
        skip_synced: If true, skips files that have already been synced
            as indicated by a .wandb.synced marker file in the same directory.
        skip_online: If true, skips online runs (determined by folder name).
        verbose: Verbose mode for printing more info.
        parallelism: Max number of runs to sync at a time.
    """
    tag_replacements = _parse_replace_tags(replace_tags)

    singleton = wandb_setup.singleton()

    try:
        cwd = pathlib.Path.cwd()
    except OSError:
        cwd = None

    ask_for_confirmation = False
    if not paths:
        paths = [pathlib.Path(singleton.settings.wandb_dir)]
        ask_for_confirmation = not skip_confirmation

    wandb_files = _find_wandb_files(
        paths,
        skip_synced=skip_synced,
        skip_online=skip_online,
        verbose=verbose,
    )

    if not wandb_files:
        term.termlog("No runs to sync.")
        return

    if dry_run:
        term.termlog(f"Would sync {len(wandb_files)} run(s):")
        _print_sorted_paths(wandb_files, verbose=verbose, root=cwd)
        return

    term.termlog(f"Syncing {len(wandb_files)} run(s):")
    _print_sorted_paths(wandb_files, verbose=verbose, root=cwd)

    if ask_for_confirmation and not term.confirm("Sync the listed runs?"):
        return

    # Authenticate the session. This updates the singleton settings credentials.
    if not wbauth.authenticate_session(
        host=singleton.settings.base_url,
        source="wandb sync",
        no_offline=True,
    ):
        term.termlog("Not authenticated.")
        return

    service = singleton.ensure_service()
    printer = new_printer()
    singleton.asyncer.run(
        lambda: _do_sync(
            wandb_files,
            cwd=cwd,
            live=live,
            service=service,
            entity=entity,
            project=project,
            run_id=run_id,
            job_type=job_type,
            tag_replacements=tag_replacements,
            settings=singleton.settings,
            printer=printer,
            parallelism=parallelism,
        )
    )


def _parse_replace_tags(replace_tags: str) -> dict[str, str]:
    """Parse the --replace-tags argument to wandb sync."""
    if not replace_tags:
        return {}

    tag_replacements: dict[str, str] = {}

    for pair in replace_tags.split(","):
        if "=" not in pair:
            raise ValueError(
                f"Invalid --replace-tags format: {pair}. Expected 'old=new'."
            )

        old_tag, new_tag = pair.split("=", 1)
        tag_replacements[old_tag.strip()] = new_tag.strip()

    return tag_replacements


async def _do_sync(
    wandb_files: set[pathlib.Path],
    *,
    cwd: pathlib.Path | None,
    live: bool,
    service: ServiceConnection,
    entity: str,
    project: str,
    run_id: str,
    job_type: str,
    tag_replacements: dict[str, str],
    settings: wandb.Settings,
    printer: Printer,
    parallelism: int,
) -> None:
    """Sync the specified files.

    This is factored out to make the progress animation testable.
    """
    init_handle = await service.init_sync(
        wandb_files,
        settings,
        cwd=cwd,
        live=live,
        entity=entity,
        project=project,
        run_id=run_id,
        job_type=job_type,
        tag_replacements=tag_replacements,
    )
    init_result = await init_handle.wait_async(timeout=5)

    sync_handle = await service.sync(init_result.id, parallelism=parallelism)

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

        self._rate_limit = ratelimit.Cooldown(_POLL_WAIT_SECONDS)
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
        for msg in response.messages:
            self._printer.display(msg.content, level=msg.severity)
        self._done.set()

    async def _show_progress_until_done(self) -> None:
        """Show rate-limited status updates until _done is set."""
        with progress_printer(self._printer, "Syncing...") as progress:
            while not await self._rate_limit_check_done():
                handle = await self._service.sync_status(self._id)
                response = await handle.wait_async(timeout=None)

                for msg in response.new_messages:
                    self._printer.display(msg.content, level=msg.severity)
                progress.update(list(response.stats))

    async def _rate_limit_check_done(self) -> bool:
        """Wait for rate limit and return whether _done is set."""
        await asyncio_compat.race(
            self._rate_limit.wait(),
            self._done.wait(),
        )

        return self._done.is_set()


def _find_wandb_files(
    paths: Iterable[pathlib.Path],
    *,
    skip_synced: bool,
    skip_online: bool,
    verbose: bool,
) -> set[pathlib.Path]:
    """Finds all unique .wandb files selected by the paths.

    Prints whether any files were skipped.

    Returns:
        The .wandb files to sync.
    """
    unique_files = _to_unique_files(
        [file for path in paths for file in _expand_wandb_files(path)],
        verbose=verbose,
    )

    filtered_files: set[pathlib.Path] = set()
    skipped_synced = 0
    skipped_online = 0

    for file in unique_files:
        if skip_synced and _is_synced(file):
            skipped_synced += 1
            continue
        if skip_online and _is_online(file):
            skipped_online += 1
            continue

        filtered_files.add(file)

    if skipped_synced:
        term.termlog(
            f"Skipped {skipped_synced} synced run(s)."
            + " Include with --no-skip-synced.",
        )
    if skipped_online:
        term.termlog(
            f"Skipped {skipped_online} online run(s)."
            + " Include with --no-skip-online.",
        )

    return filtered_files


def _to_unique_files(
    paths: list[pathlib.Path],
    *,
    verbose: bool,
) -> set[pathlib.Path]:
    """Returns paths with duplicates removed.

    Determines file equality the same way as os.path.samefile().
    """
    id_to_path: dict[tuple[int, int], pathlib.Path] = dict()

    # Sort in reverse so that the last path written to the map is
    # alphabetically earliest.
    for path in sorted(paths, reverse=True):
        try:
            stat = path.stat()
        except OSError as e:
            term.termerror(f"Failed to stat {path}: {e}")
            continue

        id = (stat.st_ino, stat.st_dev)

        if verbose and (other_path := id_to_path.get(id)):
            term.termlog(f"{path} is the same as {other_path}")

        id_to_path[id] = path

    return set(id_to_path.values())


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
        # The path looks like a wandb/ directory containing runs.
        yield from path.glob("*/*.wandb")
    else:
        # The path looks like a run directory.
        yield first_file
        yield from files_in_run_directory


def _is_synced(path: pathlib.Path) -> bool:
    """Returns whether the .wandb file is synced."""
    return path.with_suffix(".wandb.synced").exists()


def _is_online(path: pathlib.Path) -> bool:
    """Returns whether the .wandb file is for an online run.

    Online run directories are named like "run-..." and offline runs
    are named like "offline-run-...".
    """
    try:
        return not path.parent.resolve().name.startswith("offline-")
    except OSError:
        return False


def _print_sorted_paths(
    paths: Iterable[pathlib.Path],
    verbose: bool,
    *,
    root: pathlib.Path | None,
) -> None:
    """Print file paths, sorting them and truncating the list if needed.

    Args:
        paths: Paths to print. Must be absolute with symlinks resolved.
        verbose: If true, doesn't truncate paths.
        root: A root directory for making paths relative.
    """
    # Prefer to print paths relative to the current working directory.
    formatted_paths: list[str] = []
    for path in paths:
        formatted_path = str(path)

        if root:
            with contextlib.suppress(ValueError):
                formatted_path = str(path.relative_to(root))

        formatted_paths.append(formatted_path)

    sorted_paths = sorted(formatted_paths)
    max_lines = len(sorted_paths) if verbose else _MAX_LIST_LINES

    for i in range(min(len(sorted_paths), max_lines)):
        term.termlog(f"  {sorted_paths[i]}")

    if len(sorted_paths) > max_lines:
        remaining = len(sorted_paths) - max_lines
        term.termlog(f"  +{remaining:,d} more (pass --verbose to see all)")
