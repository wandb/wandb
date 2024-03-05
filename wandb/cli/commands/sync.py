import datetime
import shutil
import sys

import click

import wandb
from wandb.cli.commands.login import login
from wandb.cli.utils.api import _get_cling_api
from wandb.cli.utils.errors import display_error
from wandb.cli.utils.logger import get_wandb_cli_log_path
from wandb.sync import SyncManager, get_run_from_path, get_runs


@click.command(
    name="sync",
    context_settings={"default_map": {}},
    help="Upload an offline training directory to W&B",
)
@click.pass_context
@click.argument("path", nargs=-1, type=click.Path(exists=True))
@click.option("--view", is_flag=True, default=False, help="View runs", hidden=True)
@click.option("--verbose", is_flag=True, default=False, help="Verbose", hidden=True)
@click.option("--id", "run_id", help="The run you want to upload to.")
@click.option("--project", "-p", help="The project you want to upload to.")
@click.option("--entity", "-e", help="The entity to scope to.")
@click.option(
    "--job_type",
    "job_type",
    help="Specifies the type of run for grouping related runs together.",
)
@click.option(
    "--sync-tensorboard/--no-sync-tensorboard",
    is_flag=True,
    default=None,
    help="Stream tfevent files to wandb.",
)
@click.option("--include-globs", help="Comma separated list of globs to include.")
@click.option("--exclude-globs", help="Comma separated list of globs to exclude.")
@click.option(
    "--include-online/--no-include-online",
    is_flag=True,
    default=None,
    help="Include online runs",
)
@click.option(
    "--include-offline/--no-include-offline",
    is_flag=True,
    default=None,
    help="Include offline runs",
)
@click.option(
    "--include-synced/--no-include-synced",
    is_flag=True,
    default=None,
    help="Include synced runs",
)
@click.option(
    "--mark-synced/--no-mark-synced",
    is_flag=True,
    default=True,
    help="Mark runs as synced",
)
@click.option("--sync-all", is_flag=True, default=False, help="Sync all runs")
@click.option("--clean", is_flag=True, default=False, help="Delete synced runs")
@click.option(
    "--clean-old-hours",
    default=24,
    help="Delete runs created before this many hours. To be used alongside --clean flag.",
    type=int,
)
@click.option(
    "--clean-force",
    is_flag=True,
    default=False,
    help="Clean without confirmation prompt.",
)
@click.option("--ignore", hidden=True)
@click.option("--show", default=5, help="Number of runs to show")
@click.option("--append", is_flag=True, default=False, help="Append run")
@click.option("--skip-console", is_flag=True, default=False, help="Skip console logs")
@display_error
def sync(  # noqa: C901
    ctx,
    path=None,
    view=None,
    verbose=None,
    run_id=None,
    project=None,
    entity=None,
    job_type=None,  # trace this back to SyncManager
    sync_tensorboard=None,
    include_globs=None,
    exclude_globs=None,
    include_online=None,
    include_offline=None,
    include_synced=None,
    mark_synced=None,
    sync_all=None,
    ignore=None,
    show=None,
    clean=None,
    clean_old_hours=24,
    clean_force=None,
    append=None,
    skip_console=None,
):
    api = _get_cling_api()
    if api.api_key is None:
        wandb.termlog("Login to W&B to sync offline runs")
        ctx.invoke(login, no_offline=True)
        api = _get_cling_api(reset=True)

    if ignore:
        exclude_globs = ignore
    if include_globs:
        include_globs = include_globs.split(",")
    if exclude_globs:
        exclude_globs = exclude_globs.split(",")

    def _summary():
        all_items = get_runs(
            include_online=True,
            include_offline=True,
            include_synced=True,
            include_unsynced=True,
        )
        sync_items = get_runs(
            include_online=include_online if include_online is not None else True,
            include_offline=include_offline if include_offline is not None else True,
            include_synced=include_synced if include_synced is not None else False,
            include_unsynced=True,
            exclude_globs=exclude_globs,
            include_globs=include_globs,
        )
        synced = []
        unsynced = []
        for item in all_items:
            (synced if item.synced else unsynced).append(item)
        if sync_items:
            wandb.termlog(f"Number of runs to be synced: {len(sync_items)}")
            if show and show < len(sync_items):
                wandb.termlog(f"Showing {show} runs to be synced:")
            for item in sync_items[: (show or len(sync_items))]:
                wandb.termlog(f"  {item}")
        else:
            wandb.termlog("No runs to be synced.")
        if synced:
            clean_cmd = click.style("wandb sync --clean", fg="yellow")
            wandb.termlog(
                f"NOTE: use {clean_cmd} to delete {len(synced)} synced runs from local directory."
            )
        if unsynced:
            sync_cmd = click.style("wandb sync --sync-all", fg="yellow")
            wandb.termlog(
                f"NOTE: use {sync_cmd} to sync {len(unsynced)} unsynced runs from local directory."
            )

    def _sync_path(_path, _sync_tensorboard):
        if run_id and len(_path) > 1:
            wandb.termerror("id can only be set for a single run.")
            sys.exit(1)
        log_path = get_wandb_cli_log_path()
        sm = SyncManager(
            project=project,
            entity=entity,
            run_id=run_id,
            job_type=job_type,
            mark_synced=mark_synced,
            app_url=api.app_url,
            view=view,
            verbose=verbose,
            sync_tensorboard=_sync_tensorboard,
            log_path=log_path,
            append=append,
            skip_console=skip_console,
        )
        for p in _path:
            sm.add(p)
        sm.start()
        while not sm.is_done():
            _ = sm.poll()

    def _sync_all():
        sync_items = get_runs(
            include_online=include_online if include_online is not None else True,
            include_offline=include_offline if include_offline is not None else True,
            include_synced=include_synced if include_synced is not None else False,
            include_unsynced=True,
            exclude_globs=exclude_globs,
            include_globs=include_globs,
        )
        if not sync_items:
            wandb.termerror("Nothing to sync.")
        else:
            # When syncing run directories, default to not syncing tensorboard
            sync_tb = sync_tensorboard if sync_tensorboard is not None else False
            _sync_path(sync_items, sync_tb)

    def _clean():
        if path:
            runs = list(map(get_run_from_path, path))
            if not clean_force:
                click.confirm(
                    click.style(
                        f"Are you sure you want to remove {len(runs)} runs?",
                        bold=True,
                    ),
                    abort=True,
                )
            for run in runs:
                shutil.rmtree(run.path)
            click.echo(click.style("Success!", fg="green"))
            return
        runs = get_runs(
            include_online=include_online if include_online is not None else True,
            include_offline=include_offline if include_offline is not None else True,
            include_synced=include_synced if include_synced is not None else True,
            include_unsynced=False,
            exclude_globs=exclude_globs,
            include_globs=include_globs,
        )
        since = datetime.datetime.now() - datetime.timedelta(hours=clean_old_hours)
        old_runs = [run for run in runs if run.datetime < since]
        old_runs.sort(key=lambda _run: _run.datetime)
        if old_runs:
            click.echo(
                f"Found {len(runs)} runs, {len(old_runs)} are older than {clean_old_hours} hours"
            )
            for run in old_runs:
                click.echo(run.path)
            if not clean_force:
                click.confirm(
                    click.style(
                        f"Are you sure you want to remove {len(old_runs)} runs?",
                        bold=True,
                    ),
                    abort=True,
                )
            for run in old_runs:
                shutil.rmtree(run.path)
            click.echo(click.style("Success!", fg="green"))
        else:
            click.echo(
                click.style(
                    f"No runs older than {clean_old_hours} hours found", fg="red"
                )
            )

    if sync_all:
        _sync_all()
    elif clean:
        _clean()
    elif path:
        # When syncing a specific path, default to syncing tensorboard
        sync_tb = sync_tensorboard if sync_tensorboard is not None else True
        _sync_path(path, sync_tb)
    else:
        _summary()


@click.command("gc", hidden=True, context_settings={"ignore_unknown_options": True})
@click.argument("args", nargs=-1)
def gc(args):
    click.echo(
        "`wandb gc` command has been removed. Use `wandb sync --clean` to clean up synced runs."
    )
