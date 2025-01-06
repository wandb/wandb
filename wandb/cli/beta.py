"""Beta versions of wandb CLI commands.

These commands are experimental and may change or be removed in future versions.
"""

from __future__ import annotations

import pathlib
import sys

import click

import wandb
from wandb.errors import UsageError, WandbCoreNotAvailableError
from wandb.sdk.wandb_sync import _sync
from wandb.util import get_core_path


@click.group()
def beta():
    """Beta versions of wandb CLI commands. Requires wandb-core."""
    # this is the future that requires wandb-core!
    import wandb.env

    wandb._sentry.configure_scope(process_context="wandb_beta")

    if wandb.env.is_require_legacy_service():
        raise UsageError(
            "wandb beta commands can only be used with wandb-core. "
            f"Please make sure that `{wandb.env._REQUIRE_LEGACY_SERVICE}` is not set."
        )

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
    name="sync",
    context_settings={"default_map": {}},
    help="Upload a training run to W&B",
)
@click.pass_context
@click.argument("wandb_dir", nargs=1, type=click.Path(exists=True))
@click.option("--id", "run_id", help="The run you want to upload to.")
@click.option("--project", "-p", help="The project you want to upload to.")
@click.option("--entity", "-e", help="The entity to scope to.")
@click.option("--skip-console", is_flag=True, default=False, help="Skip console logs")
@click.option("--append", is_flag=True, default=False, help="Append run")
@click.option(
    "--include",
    "-i",
    help="Glob to include. Can be used multiple times.",
    multiple=True,
)
@click.option(
    "--exclude",
    "-e",
    help="Glob to exclude. Can be used multiple times.",
    multiple=True,
)
@click.option(
    "--mark-synced/--no-mark-synced",
    is_flag=True,
    default=True,
    help="Mark runs as synced",
)
@click.option(
    "--skip-synced/--no-skip-synced",
    is_flag=True,
    default=True,
    help="Skip synced runs",
)
@click.option(
    "--dry-run", is_flag=True, help="Perform a dry run without uploading anything."
)
def sync_beta(  # noqa: C901
    ctx,
    wandb_dir=None,
    run_id: str | None = None,
    project: str | None = None,
    entity: str | None = None,
    skip_console: bool = False,
    append: bool = False,
    include: str | None = None,
    exclude: str | None = None,
    skip_synced: bool = True,
    mark_synced: bool = True,
    dry_run: bool = False,
) -> None:
    import concurrent.futures
    from multiprocessing import cpu_count

    paths = set()

    # TODO: test file discovery logic
    # include and exclude globs are evaluated relative to the provided base_path
    if include:
        for pattern in include:
            matching_dirs = list(pathlib.Path(wandb_dir).glob(pattern))
            for d in matching_dirs:
                if not d.is_dir():
                    continue
                wandb_files = [p for p in d.glob("*.wandb") if p.is_file()]
                if len(wandb_files) > 1:
                    wandb.termwarn(
                        f"Multiple wandb files found in directory {d}, skipping"
                    )
                elif len(wandb_files) == 1:
                    paths.add(d)
    else:
        paths.update({p.parent for p in pathlib.Path(wandb_dir).glob("**/*.wandb")})

    for pattern in exclude:
        matching_dirs = list(pathlib.Path(wandb_dir).glob(pattern))
        for d in matching_dirs:
            if not d.is_dir():
                continue
            if d in paths:
                paths.remove(d)

    # remove paths that are already synced, if requested
    if skip_synced:
        synced_paths = set()
        for path in paths:
            wandb_synced_files = [p for p in path.glob("*.wandb.synced") if p.is_file()]
            if len(wandb_synced_files) > 1:
                wandb.termwarn(
                    f"Multiple wandb.synced files found in directory {path}, skipping"
                )
            elif len(wandb_synced_files) == 1:
                synced_paths.add(path)
        paths -= synced_paths

    if run_id and len(paths) > 1:
        # TODO: handle this more gracefully
        click.echo("id can only be set for a single run.", err=True)
        sys.exit(1)

    if not paths:
        click.echo("No runs to sync.")
        return

    click.echo("Found runs:")
    for path in paths:
        click.echo(f"  {path}")

    if dry_run:
        return

    wandb.setup()

    # TODO: make it thread-safe in the Rust code
    with concurrent.futures.ProcessPoolExecutor(
        max_workers=min(len(paths), cpu_count())
    ) as executor:
        futures = []
        for path in paths:
            # we already know there is only one wandb file in the directory
            wandb_file = [p for p in path.glob("*.wandb") if p.is_file()][0]
            future = executor.submit(
                _sync,
                wandb_file,
                run_id=run_id,
                project=project,
                entity=entity,
                skip_console=skip_console,
                append=append,
                mark_synced=mark_synced,
            )
            futures.append(future)

        # Wait for tasks to complete
        for _ in concurrent.futures.as_completed(futures):
            pass
