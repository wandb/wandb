#!/usr/bin/env python

import asyncio
import configparser
import datetime
import getpass
import json
import logging
import os
import pathlib
import shlex
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import traceback
from functools import wraps
from typing import Any, Dict, Optional

import click
import yaml
from click.exceptions import ClickException

# pycreds has a find_executable that works in windows
from dockerpycreds.utils import find_executable

import wandb
import wandb.env

# from wandb.old.core import wandb_dir
import wandb.errors
import wandb.sdk.verify.verify as wandb_verify
from wandb import Config, Error, env, util, wandb_agent, wandb_sdk
from wandb.apis import InternalApi, PublicApi
from wandb.apis.public import RunQueue
from wandb.errors import UsageError, WandbCoreNotAvailableError
from wandb.integration.magic import magic_install
from wandb.sdk.artifacts.artifact_file_cache import get_artifact_file_cache
from wandb.sdk.launch import utils as launch_utils
from wandb.sdk.launch._launch_add import _launch_add
from wandb.sdk.launch.errors import ExecutionError, LaunchError
from wandb.sdk.launch.sweeps import utils as sweep_utils
from wandb.sdk.launch.sweeps.scheduler import Scheduler
from wandb.sdk.lib import filesystem
from wandb.sdk.lib.wburls import wburls
from wandb.sync import SyncManager, get_run_from_path, get_runs
from wandb.util import get_core_path

# Send cli logs to wandb/debug-cli.<username>.log by default and fallback to a temp dir.
_wandb_dir = wandb.old.core.wandb_dir(env.get_dir())
if not os.path.exists(_wandb_dir):
    _wandb_dir = tempfile.gettempdir()

try:
    _username = getpass.getuser()
except KeyError:
    # getuser() could raise KeyError in restricted environments like
    # chroot jails or docker containers. Return user id in these cases.
    _username = str(os.getuid())

_wandb_log_path = os.path.join(_wandb_dir, f"debug-cli.{_username}.log")

logging.basicConfig(
    filename=_wandb_log_path,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logging.basicConfig(stream=sys.stdout, level=logging.INFO)
logger = logging.getLogger("wandb")

# Click Contexts
CONTEXT = {"default_map": {}}
RUN_CONTEXT = {
    "default_map": {},
    "allow_extra_args": True,
    "ignore_unknown_options": True,
}


def cli_unsupported(argument):
    wandb.termerror(f"Unsupported argument `{argument}`")
    sys.exit(1)


class ClickWandbException(ClickException):
    def format_message(self):
        # log_file = util.get_log_file_path()
        log_file = ""
        orig_type = f"{self.orig_type.__module__}.{self.orig_type.__name__}"
        if issubclass(self.orig_type, Error):
            return click.style(str(self.message), fg="red")
        else:
            return (
                f"An Exception was raised, see {log_file} for full traceback.\n"
                f"{orig_type}: {self.message}"
            )


def display_error(func):
    """Function decorator for catching common errors and re-raising as wandb.Error."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except wandb.Error as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
            logger.error("".join(lines))
            wandb.termerror(f"Find detailed error logs at: {_wandb_log_path}")
            click_exc = ClickWandbException(e)
            click_exc.orig_type = exc_type
            raise click_exc.with_traceback(sys.exc_info()[2])

    return wrapper


_api = None  # caching api instance allows patching from unit tests


def _get_cling_api(reset=None):
    """Get a reference to the internal api with cling settings."""
    # TODO: move CLI to wandb-core backend
    wandb.require("legacy-service")

    global _api
    if reset:
        _api = None
        wandb_sdk.wandb_setup._setup(_reset=True)
    if _api is None:
        # TODO(jhr): make a settings object that is better for non runs.
        # only override the necessary setting
        wandb.setup(settings=dict(_cli_only_mode=True))
        _api = InternalApi()
    return _api


def prompt_for_project(ctx, entity):
    """Ask the user for a project, creating one if necessary."""
    result = ctx.invoke(projects, entity=entity, display=False)
    api = _get_cling_api()
    try:
        if len(result) == 0:
            project = click.prompt("Enter a name for your first project")
            # description = editor()
            project = api.upsert_project(project, entity=entity)["name"]
        else:
            project_names = [project["name"] for project in result] + ["Create New"]
            wandb.termlog("Which project should we use?")
            result = util.prompt_choices(project_names)
            if result:
                project = result
            else:
                project = "Create New"
            # TODO: check with the server if the project exists
            if project == "Create New":
                project = click.prompt(
                    "Enter a name for your new project", value_proc=api.format_project
                )
                # description = editor()
                project = api.upsert_project(project, entity=entity)["name"]

    except wandb.errors.CommError as e:
        raise ClickException(str(e))

    return project


class RunGroup(click.Group):
    @display_error
    def get_command(self, ctx, cmd_name):
        # TODO: check if cmd_name is a file in the current dir and not require `run`?
        rv = click.Group.get_command(self, ctx, cmd_name)
        if rv is not None:
            return rv
        return None


@click.command(cls=RunGroup, invoke_without_command=True)
@click.version_option(version=wandb.__version__)
@click.pass_context
def cli(ctx):
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@cli.command(context_settings=CONTEXT, help="List projects", hidden=True)
@click.option(
    "--entity",
    "-e",
    default=None,
    envvar=env.ENTITY,
    help="The entity to scope the listing to.",
)
@display_error
def projects(entity, display=True):
    api = _get_cling_api()
    projects = api.list_projects(entity=entity)
    if len(projects) == 0:
        message = "No projects found for {}".format(entity)
    else:
        message = 'Latest projects for "{}"'.format(entity)
    if display:
        click.echo(click.style(message, bold=True))
        for project in projects:
            click.echo(
                "".join(
                    (
                        click.style(project["name"], fg="blue", bold=True),
                        " - ",
                        str(project["description"] or "").split("\n")[0],
                    )
                )
            )
    return projects


@cli.command(context_settings=CONTEXT, help="Login to Weights & Biases")
@click.argument("key", nargs=-1)
@click.option("--cloud", is_flag=True, help="Login to the cloud instead of local")
@click.option("--host", default=None, help="Login to a specific instance of W&B")
@click.option(
    "--relogin", default=None, is_flag=True, help="Force relogin if already logged in."
)
@click.option("--anonymously", default=False, is_flag=True, help="Log in anonymously")
@click.option("--verify", default=False, is_flag=True, help="Verify login credentials")
@display_error
def login(key, host, cloud, relogin, anonymously, verify, no_offline=False):
    # TODO: move CLI to wandb-core backend
    wandb.require("legacy-service")

    # TODO: handle no_offline
    anon_mode = "must" if anonymously else "never"

    wandb_sdk.wandb_login._handle_host_wandb_setting(host, cloud)
    # A change in click or the test harness means key can be none...
    key = key[0] if key is not None and len(key) > 0 else None
    if key:
        relogin = True

    login_settings = dict(
        _cli_only_mode=True,
        _disable_viewer=relogin and not verify,
        anonymous=anon_mode,
    )
    if host is not None:
        login_settings["base_url"] = host

    try:
        wandb.setup(settings=login_settings)
    except TypeError as e:
        wandb.termerror(str(e))
        sys.exit(1)

    wandb.login(
        relogin=relogin,
        key=key,
        anonymous=anon_mode,
        host=host,
        force=True,
        verify=verify,
    )


@cli.command(
    context_settings=CONTEXT, help="Run a wandb service", name="service", hidden=True
)
@click.option(
    "--sock-port", default=None, type=int, help="The host port to bind socket service."
)
@click.option("--port-filename", default=None, help="Save allocated port to file.")
@click.option("--address", default=None, help="The address to bind service.")
@click.option("--pid", default=None, type=int, help="The parent process id to monitor.")
@click.option("--debug", is_flag=True, help="log debug info")
@display_error
def service(
    sock_port=None,
    port_filename=None,
    address=None,
    pid=None,
    debug=False,
):
    from wandb.sdk.service.server import WandbServer

    server = WandbServer(
        sock_port=sock_port,
        port_fname=port_filename,
        address=address,
        pid=pid,
        debug=debug,
    )
    server.serve()


@cli.command(
    context_settings=CONTEXT, help="Configure a directory with Weights & Biases"
)
@click.option("--project", "-p", help="The project to use.")
@click.option("--entity", "-e", help="The entity to scope the project to.")
# TODO(jhr): Enable these with settings rework
# @click.option("--setting", "-s", help="enable an arbitrary setting.", multiple=True)
# @click.option('--show', is_flag=True, help="Show settings")
@click.option("--reset", is_flag=True, help="Reset settings")
@click.option(
    "--mode",
    "-m",
    help=' Can be "online", "offline" or "disabled". Defaults to online.',
)
@click.pass_context
@display_error
def init(ctx, project, entity, reset, mode):
    from wandb.old.core import __stage_dir__, _set_stage_dir, wandb_dir

    if __stage_dir__ is None:
        _set_stage_dir("wandb")

    # non-interactive init
    if reset or project or entity or mode:
        api = InternalApi()
        if reset:
            api.clear_setting("entity", persist=True)
            api.clear_setting("project", persist=True)
            api.clear_setting("mode", persist=True)
            # TODO(jhr): clear more settings?
        if entity:
            api.set_setting("entity", entity, persist=True)
        if project:
            api.set_setting("project", project, persist=True)
        if mode:
            api.set_setting("mode", mode, persist=True)
        return

    if os.path.isdir(wandb_dir()) and os.path.exists(
        os.path.join(wandb_dir(), "settings")
    ):
        click.confirm(
            click.style(
                "This directory has been configured previously, should we re-configure it?",
                bold=True,
            ),
            abort=True,
        )
    else:
        click.echo(
            click.style("Let's setup this directory for W&B!", fg="green", bold=True)
        )
    api = _get_cling_api()
    if api.api_key is None:
        ctx.invoke(login)
        api = _get_cling_api(reset=True)

    viewer = api.viewer()

    # Viewer can be `None` in case your API information became invalid, or
    # in testing if you switch hosts.
    if not viewer:
        click.echo(
            click.style(
                "Your login information seems to be invalid: can you log in again please?",
                fg="red",
                bold=True,
            )
        )
        ctx.invoke(login)
        api = _get_cling_api(reset=True)

    # This shouldn't happen.
    viewer = api.viewer()
    if not viewer:
        click.echo(
            click.style(
                "We're sorry, there was a problem logging you in. "
                "Please send us a note at support@wandb.com and tell us how this happened.",
                fg="red",
                bold=True,
            )
        )
        sys.exit(1)

    # At this point we should be logged in successfully.
    if len(viewer["teams"]["edges"]) > 1:
        team_names = [e["node"]["name"] for e in viewer["teams"]["edges"]] + [
            "Manual entry"
        ]
        wandb.termlog(
            "Which team should we use?",
        )
        result = util.prompt_choices(team_names)
        # result can be empty on click
        if result:
            entity = result
        else:
            entity = "Manual Entry"
        if entity == "Manual Entry":
            entity = click.prompt("Enter the name of the team you want to use")
    else:
        entity = viewer.get("entity") or click.prompt(
            "What username or team should we use?"
        )

    # TODO: this error handling sucks and the output isn't pretty
    try:
        project = prompt_for_project(ctx, entity)
    except ClickWandbException:
        raise ClickException(f"Could not find team: {entity}")

    api.set_setting("entity", entity, persist=True)
    api.set_setting("project", project, persist=True)
    api.set_setting("base_url", api.settings().get("base_url"), persist=True)

    filesystem.mkdir_exists_ok(wandb_dir())
    with open(os.path.join(wandb_dir(), ".gitignore"), "w") as file:
        file.write("*\n!settings")

    click.echo(
        click.style("This directory is configured!  Next, track a run:\n", fg="green")
        + textwrap.dedent(
            """\
        * In your training script:
            {code1}
            {code2}
        * then `{run}`.
        """
        ).format(
            code1=click.style("import wandb", bold=True),
            code2=click.style('wandb.init(project="{}")'.format(project), bold=True),
            run=click.style("python <train.py>", bold=True),
        )
    )


@cli.group()
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
    context_settings=CONTEXT,
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
@display_error
def sync_beta(
    ctx,
    wandb_dir=None,
    run_id: Optional[str] = None,
    project: Optional[str] = None,
    entity: Optional[str] = None,
    skip_console: bool = False,
    append: bool = False,
    include: Optional[str] = None,
    exclude: Optional[str] = None,
    skip_synced: bool = True,
    mark_synced: bool = True,
    dry_run: bool = False,
):
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
                    print(f"Multiple wandb files found in directory {d}, skipping")
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
                print(
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

    wandb.sdk.wandb_setup.setup()

    # TODO: make it thread-safe in the Rust code
    with concurrent.futures.ProcessPoolExecutor(
        max_workers=min(len(paths), cpu_count())
    ) as executor:
        futures = []
        for path in paths:
            # we already know there is only one wandb file in the directory
            wandb_file = [p for p in path.glob("*.wandb") if p.is_file()][0]
            future = executor.submit(
                wandb._sync,
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


@cli.command(
    context_settings=CONTEXT, help="Upload an offline training directory to W&B"
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
def sync(
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
    if not api.is_authenticated:
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
            log_path=_wandb_log_path,
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


@cli.command(
    context_settings=CONTEXT,
    help="Initialize a hyperparameter sweep. Search for hyperparameters that optimizes a cost function of a machine learning model by testing various combinations.",
)
@click.option(
    "--project",
    "-p",
    default=None,
    help="""The name of the project where W&B runs created from the sweep are sent to. If the project is not specified, the run is sent to a project labeled Uncategorized.""",
)
@click.option(
    "--entity",
    "-e",
    default=None,
    help="""The username or team name where you want to send W&B runs created by the sweep to. Ensure that the entity you specify already exists. If you don't specify an entity, the run will be sent to your default entity, which is usually your username.""",
)
@click.option("--controller", is_flag=True, default=False, help="Run local controller")
@click.option("--verbose", is_flag=True, default=False, help="Display verbose output")
@click.option(
    "--name",
    default=None,
    help="The name of the sweep. The sweep ID is used if no name is specified.",
)
@click.option("--program", default=None, help="Set sweep program")
@click.option("--settings", default=None, help="Set sweep settings", hidden=True)
@click.option("--update", default=None, help="Update pending sweep")
@click.option(
    "--stop",
    is_flag=True,
    default=False,
    help="Finish a sweep to stop running new runs and let currently running runs finish.",
)
@click.option(
    "--cancel",
    is_flag=True,
    default=False,
    help="Cancel a sweep to kill all running runs and stop running new runs.",
)
@click.option(
    "--pause",
    is_flag=True,
    default=False,
    help="Pause a sweep to temporarily stop running new runs.",
)
@click.option(
    "--resume",
    is_flag=True,
    default=False,
    help="Resume a sweep to continue running new runs.",
)
@click.option(
    "--prior_run",
    "-R",
    "prior_runs",
    multiple=True,
    default=None,
    help="ID of an existing run to add to this sweep",
)
@click.argument("config_yaml_or_sweep_id")
@click.pass_context
@display_error
def sweep(
    ctx,
    project,
    entity,
    controller,
    verbose,
    name,
    program,
    settings,
    update,
    stop,
    cancel,
    pause,
    resume,
    prior_runs,
    config_yaml_or_sweep_id,
):
    state_args = "stop", "cancel", "pause", "resume"
    lcls = locals()
    is_state_change_command = sum(lcls[k] for k in state_args)
    if is_state_change_command > 1:
        raise Exception("Only one state flag (stop/cancel/pause/resume) is allowed.")
    elif is_state_change_command == 1:
        sweep_id = config_yaml_or_sweep_id
        api = _get_cling_api()
        if not api.is_authenticated:
            wandb.termlog("Login to W&B to use the sweep feature")
            ctx.invoke(login, no_offline=True)
            api = _get_cling_api(reset=True)
        parts = dict(entity=entity, project=project, name=sweep_id)
        err = sweep_utils.parse_sweep_id(parts)
        if err:
            wandb.termerror(err)
            return
        entity = parts.get("entity") or entity
        project = parts.get("project") or project
        sweep_id = parts.get("name") or sweep_id
        state = [s for s in state_args if lcls[s]][0]
        ings = {
            "stop": "Stopping",
            "cancel": "Cancelling",
            "pause": "Pausing",
            "resume": "Resuming",
        }
        wandb.termlog(f"{ings[state]} sweep {entity}/{project}/{sweep_id}")
        getattr(api, "{}_sweep".format(state))(sweep_id, entity=entity, project=project)
        wandb.termlog("Done.")
        return
    else:
        config_yaml = config_yaml_or_sweep_id

    def _parse_settings(settings):
        """Parse settings from json or comma separated assignments."""
        ret = {}
        # TODO(jhr): merge with magic:_parse_magic
        if settings.find("=") > 0:
            for item in settings.split(","):
                kv = item.split("=")
                if len(kv) != 2:
                    wandb.termwarn(
                        "Unable to parse sweep settings key value pair", repeat=False
                    )
                ret.update(dict([kv]))
            return ret
        wandb.termwarn("Unable to parse settings parameter", repeat=False)
        return ret

    api = _get_cling_api()
    if not api.is_authenticated:
        wandb.termlog("Login to W&B to use the sweep feature")
        ctx.invoke(login, no_offline=True)
        api = _get_cling_api(reset=True)

    sweep_obj_id = None
    if update:
        parts = dict(entity=entity, project=project, name=update)
        err = sweep_utils.parse_sweep_id(parts)
        if err:
            wandb.termerror(err)
            return
        entity = parts.get("entity") or entity
        project = parts.get("project") or project
        sweep_id = parts.get("name") or update

        has_project = (project or api.settings("project")) is not None
        has_entity = (entity or api.settings("entity")) is not None

        termerror_msg = (
            "Sweep lookup requires a valid %s, and none was specified. \n"
            "Either set a default %s in wandb/settings, or, if invoking \n`wandb sweep` "
            "from the command line, specify the full sweep path via: \n\n"
            "    wandb sweep {username}/{projectname}/{sweepid}\n\n"
        )

        if not has_entity:
            wandb.termerror(termerror_msg % (("entity",) * 2))
            return

        if not has_project:
            wandb.termerror(termerror_msg % (("project",) * 2))
            return

        found = api.sweep(sweep_id, "{}", entity=entity, project=project)
        if not found:
            wandb.termerror(f"Could not find sweep {entity}/{project}/{sweep_id}")
            return
        sweep_obj_id = found["id"]

    action = "Updating" if sweep_obj_id else "Creating"
    wandb.termlog(f"{action} sweep from: {config_yaml}")
    config = sweep_utils.load_sweep_config(config_yaml)

    # Set or override parameters
    if name:
        config["name"] = name
    if program:
        config["program"] = program
    if settings:
        settings = _parse_settings(settings)
        if settings:
            config.setdefault("settings", {})
            config["settings"].update(settings)
    if controller:
        config.setdefault("controller", {})
        config["controller"]["type"] = "local"

    is_local = config.get("controller", {}).get("type") == "local"
    if is_local:
        from wandb import controller as wandb_controller

        tuner = wandb_controller()
        err = tuner._validate(config)
        if err:
            wandb.termerror(f"Error in sweep file: {err}")
            return

    env = os.environ
    entity = (
        entity
        or env.get("WANDB_ENTITY")
        or config.get("entity")
        or api.settings("entity")
    )
    project = (
        project
        or env.get("WANDB_PROJECT")
        or config.get("project")
        or api.settings("project")
        or util.auto_project_name(config.get("program"))
    )

    sweep_id, warnings = api.upsert_sweep(
        config,
        project=project,
        entity=entity,
        obj_id=sweep_obj_id,
        prior_runs=prior_runs,
    )
    sweep_utils.handle_sweep_config_violations(warnings)

    # Log nicely formatted sweep information
    styled_id = click.style(sweep_id, fg="yellow")
    wandb.termlog(f"{action} sweep with ID: {styled_id}")

    sweep_url = wandb_sdk.wandb_sweep._get_sweep_url(api, sweep_id)
    if sweep_url:
        styled_url = click.style(sweep_url, underline=True, fg="blue")
        wandb.termlog(f"View sweep at: {styled_url}")

    # re-probe entity and project if it was auto-detected by upsert_sweep
    entity = entity or env.get("WANDB_ENTITY")
    project = project or env.get("WANDB_PROJECT")

    if entity and project:
        sweep_path = f"{entity}/{project}/{sweep_id}"
    elif project:
        sweep_path = f"{project}/{sweep_id}"
    else:
        sweep_path = sweep_id

    if sweep_path.find(" ") >= 0:
        sweep_path = f"{sweep_path!r}"

    styled_path = click.style(f"wandb agent {sweep_path}", fg="yellow")
    wandb.termlog(f"Run sweep agent with: {styled_path}")
    if controller:
        wandb.termlog("Starting wandb controller...")
        from wandb import controller as wandb_controller

        tuner = wandb_controller(sweep_id)
        tuner.run(verbose=verbose)


@cli.command(
    context_settings=CONTEXT,
    no_args_is_help=True,
    help="Run a W&B launch sweep (Experimental).",
)
@click.option(
    "--queue",
    "-q",
    default=None,
    help="The name of a queue to push the sweep to",
)
@click.option(
    "--project",
    "-p",
    default=None,
    help="Name of the project which the agent will watch. "
    "If passed in, will override the project value passed in using a config file",
)
@click.option(
    "--entity",
    "-e",
    default=None,
    help="The entity to use. Defaults to current logged-in user",
)
@click.option(
    "--resume_id",
    "-r",
    default=None,
    help="Resume a launch sweep by passing an 8-char sweep id. Queue required",
)
@click.option(
    "--prior_run",
    "-R",
    "prior_runs",
    multiple=True,
    default=None,
    help="ID of an existing run to add to this sweep",
)
@click.argument("config", required=False, type=click.Path(exists=True))
@click.pass_context
@display_error
def launch_sweep(
    ctx,
    project,
    entity,
    queue,
    config,
    resume_id,
    prior_runs,
):
    api = _get_cling_api()
    env = os.environ
    if not api.is_authenticated:
        wandb.termlog("Login to W&B to use the sweep feature")
        ctx.invoke(login, no_offline=True)
        api = _get_cling_api(reset=True)

    entity = entity or env.get("WANDB_ENTITY") or api.settings("entity")
    if entity is None:
        wandb.termerror("Must specify entity when using launch")
        return

    project = project or env.get("WANDB_PROJECT") or api.settings("project")
    if project is None:
        wandb.termerror("A project must be configured when using launch")
        return

    # get personal username, not team name or service account, default to entity
    author = api.viewer().get("username") or entity

    # if not sweep_config XOR resume_id
    if not (config or resume_id):
        wandb.termerror("'config' and/or 'resume_id' required")
        return

    parsed_user_config = sweep_utils.load_launch_sweep_config(config)
    # Rip special keys out of config, store in scheduler run_config
    launch_args: Dict[str, Any] = parsed_user_config.pop("launch", {})
    scheduler_args: Dict[str, Any] = parsed_user_config.pop("scheduler", {})
    settings: Dict[str, Any] = scheduler_args.pop("settings", {})

    scheduler_job: Optional[str] = scheduler_args.get("job")
    if scheduler_job:
        wandb.termwarn(
            "Using a scheduler job for launch sweeps is *experimental* and may change without warning"
        )
    queue: Optional[str] = queue or launch_args.get("queue")

    sweep_config, sweep_obj_id = None, None
    if not resume_id:
        sweep_config = parsed_user_config

        # check method
        method = sweep_config.get("method")
        if scheduler_job and not method:
            sweep_config["method"] = "custom"
        elif scheduler_job and method != "custom":
            # TODO(gst): Check if using Anaconda2
            wandb.termwarn(
                "Use 'method': 'custom' in the sweep config when using scheduler jobs, "
                "or omit it entirely. For jobs using the wandb optimization engine (WandbScheduler), "
                "set the method in the sweep config under scheduler.settings.method "
            )
            settings["method"] = method

        if settings.get("method"):
            # assume WandbScheduler, and user is using this right
            sweep_config["method"] = settings["method"]

    else:  # Resuming an existing sweep
        found = api.sweep(resume_id, "{}", entity=entity, project=project)
        if not found:
            wandb.termerror(f"Could not find sweep {entity}/{project}/{resume_id}")
            return

        if found.get("state") == "RUNNING":
            wandb.termerror(
                f"Cannot resume sweep {entity}/{project}/{resume_id}, it is already running"
            )
            return

        sweep_obj_id = found["id"]
        sweep_config = yaml.safe_load(found["config"])
        wandb.termlog(f"Resuming from existing sweep {entity}/{project}/{resume_id}")
        if len(parsed_user_config.keys()) > 0:
            wandb.termwarn(
                "Sweep parameters loaded from resumed sweep, ignoring provided config"
            )

        prev_scheduler = json.loads(found.get("scheduler") or "{}")
        run_spec = json.loads(prev_scheduler.get("run_spec", "{}"))
        if (
            scheduler_job
            and run_spec.get("job")
            and run_spec.get("job") != scheduler_job
        ):
            wandb.termerror(
                f"Resuming a launch sweep with a different scheduler job is not supported. Job loaded from sweep: {run_spec.get('job')}, job in config: {scheduler_job}"
            )
            return

        prev_scheduler_args, prev_settings = sweep_utils.get_previous_args(run_spec)
        # Passed in scheduler_args and settings override previous
        scheduler_args.update(prev_scheduler_args)
        settings.update(prev_settings)
    if not queue:
        wandb.termerror(
            "Launch-sweeps require setting a 'queue', use --queue option or a 'queue' key in the 'launch' section in the config"
        )
        return

    entrypoint = Scheduler.ENTRYPOINT if not scheduler_job else None
    args = sweep_utils.construct_scheduler_args(
        return_job=scheduler_job is not None,
        sweep_config=sweep_config,
        queue=queue,
        project=project,
        author=author,
    )
    if not args:
        return

    # validate training job existence
    if not sweep_utils.check_job_exists(PublicApi(), sweep_config.get("job")):
        return False

    # validate scheduler job existence, if present
    if not sweep_utils.check_job_exists(PublicApi(), scheduler_job):
        return False

    # Set run overrides for the Scheduler
    overrides = {"run_config": {}}
    if launch_args:
        overrides["run_config"]["launch"] = launch_args
    if scheduler_args:
        overrides["run_config"]["scheduler"] = scheduler_args
    if settings:
        overrides["run_config"]["settings"] = settings

    if scheduler_job:
        overrides["run_config"]["sweep_args"] = args
    else:
        overrides["args"] = args

    # configure scheduler job resource
    resource = scheduler_args.get("resource")
    if resource:
        if resource == "local-process" and scheduler_job:
            wandb.termerror(
                "Scheduler jobs cannot be run with the 'local-process' resource"
            )
            return
        if resource == "local-process" and scheduler_args.get("docker_image"):
            wandb.termerror(
                "Scheduler jobs cannot be run with the 'local-process' resource and a docker image"
            )
            return
    else:  # no resource set, default local-process if not scheduler job, else container
        resource = "local-process" if not scheduler_job else "local-container"

    # Launch job spec for the Scheduler
    launch_scheduler_spec = launch_utils.construct_launch_spec(
        uri=Scheduler.PLACEHOLDER_URI,
        api=api,
        name="Scheduler.WANDB_SWEEP_ID",
        project=project,
        entity=entity,
        docker_image=scheduler_args.get("docker_image"),
        resource=resource,
        entry_point=entrypoint,
        resource_args=scheduler_args.get("resource_args", {}),
        repository=launch_args.get("registry", {}).get("url", None),
        job=scheduler_job,
        version=None,
        launch_config={"overrides": overrides},
        run_id="WANDB_SWEEP_ID",  # scheduler inits run with sweep_id=run_id
        author=None,  # author gets passed into scheduler override args
    )
    launch_scheduler_with_queue = json.dumps(
        {
            "queue": queue,
            "run_queue_project": launch_utils.LAUNCH_DEFAULT_PROJECT,
            "run_spec": json.dumps(launch_scheduler_spec),
        }
    )

    sweep_id, warnings = api.upsert_sweep(
        sweep_config,
        project=project,
        entity=entity,
        obj_id=sweep_obj_id,  # if resuming
        launch_scheduler=launch_scheduler_with_queue,
        state="PENDING",
        prior_runs=prior_runs,
        template_variable_values=scheduler_args.get("template_variables", None),
    )
    sweep_utils.handle_sweep_config_violations(warnings)
    # Log nicely formatted sweep information
    styled_id = click.style(sweep_id, fg="yellow")
    wandb.termlog(f"{'Resumed' if resume_id else 'Created'} sweep with ID: {styled_id}")
    sweep_url = wandb_sdk.wandb_sweep._get_sweep_url(api, sweep_id)
    if sweep_url:
        styled_url = click.style(sweep_url, underline=True, fg="blue")
        wandb.termlog(f"View sweep at: {styled_url}")
    wandb.termlog(f"Scheduler added to launch queue ({queue})")


@cli.command(help=f"Launch or queue a W&B Job. See {wburls.get('cli_launch')}")
@click.option(
    "--uri",
    "-u",
    metavar="(str)",
    default=None,
    help="Local path or git repo uri to launch. If provided this command will "
    "create a job from the specified uri.",
)
@click.option(
    "--job",
    "-j",
    metavar="(str)",
    default=None,
    help="Name of the job to launch. If passed in, launch does not require a uri.",
)
@click.option(
    "--entry-point",
    "-E",
    metavar="NAME",
    default=None,
    help="""Entry point within project. [default: main]. If the entry point is not found,
    attempts to run the project file with the specified name as a script,
    using 'python' to run .py files and the default shell (specified by
    environment variable $SHELL) to run .sh files. If passed in, will override the entrypoint value passed in using a config file.""",
)
@click.option(
    "--git-version",
    "-g",
    metavar="GIT-VERSION",
    hidden=True,
    help="Version of the project to run, as a Git commit reference for Git projects.",
)
@click.option(
    "--build-context",
    metavar="(str)",
    help="Path to the build context within the source code. Defaults to the "
    "root of the source code. Compatible only with -u.",
)
@click.option(
    "--job-name",
    "-J",
    metavar="(str)",
    default=None,
    hidden=True,
    help="Name for the job created if the -u,--uri flag is passed in.",
)
@click.option(
    "--name",
    envvar="WANDB_NAME",
    help="""Name of the run under which to launch the run. If not
    specified, a random run name will be used to launch run. If passed in, will override the name passed in using a config file.""",
)
@click.option(
    "--entity",
    "-e",
    metavar="(str)",
    default=None,
    help="""Name of the target entity which the new run will be sent to. Defaults to using the entity set by local wandb/settings folder.
    If passed in, will override the entity value passed in using a config file.""",
)
@click.option(
    "--project",
    "-p",
    metavar="(str)",
    default=None,
    help="""Name of the target project which the new run will be sent to. Defaults to using the project name given by the source uri
    or for github runs, the git repo name. If passed in, will override the project value passed in using a config file.""",
)
@click.option(
    "--resource",
    "-r",
    metavar="BACKEND",
    default=None,
    help="""Execution resource to use for run. Supported values: 'local-process', 'local-container', 'kubernetes', 'sagemaker', 'gcp-vertex'.
    This is now a required parameter if pushing to a queue with no resource configuration.
    If passed in, will override the resource value passed in using a config file.""",
)
@click.option(
    "--docker-image",
    "-d",
    default=None,
    metavar="DOCKER IMAGE",
    help="""Specific docker image you'd like to use. In the form name:tag.
    If passed in, will override the docker image value passed in using a config file.""",
)
@click.option(
    "--base-image",
    "-B",
    default=None,
    metavar="BASE IMAGE",
    help="""Docker image to run job code in. Incompatible with --docker-image.""",
)
@click.option(
    "--config",
    "-c",
    metavar="FILE",
    help="""Path to JSON file (must end in '.json') or JSON string which will be passed
    as a launch config. Dictation how the launched run will be configured.""",
)
@click.option(
    "--set-var",
    "-v",
    "cli_template_vars",
    default=None,
    multiple=True,
    help="""Set template variable values for queues with allow listing enabled,
    as key-value pairs e.g. `--set-var key1=value1 --set-var key2=value2`""",
)
@click.option(
    "--queue",
    "-q",
    is_flag=False,
    flag_value="default",
    default=None,
    help="""Name of run queue to push to. If none, launches single run directly. If supplied without
    an argument (`--queue`), defaults to queue 'default'. Else, if name supplied, specified run queue must exist under the
    project and entity supplied.""",
)
@click.option(
    "--async",
    "run_async",
    is_flag=True,
    help="""Flag to run the job asynchronously. Defaults to false, i.e. unless --async is set, wandb launch will wait for
    the job to finish. This option is incompatible with --queue; asynchronous options when running with an agent should be
    set on wandb launch-agent.""",
)
@click.option(
    "--resource-args",
    "-R",
    metavar="FILE",
    help="""Path to JSON file (must end in '.json') or JSON string which will be passed
    as resource args to the compute resource. The exact content which should be
    provided is different for each execution backend. See documentation for layout of this file.""",
)
@click.option(
    "--build",
    "-b",
    is_flag=True,
    hidden=True,
    help="Flag to build an associated job and push to queue as an image job.",
)
@click.option(
    "--repository",
    "-rg",
    is_flag=False,
    default=None,
    hidden=True,
    help="Name of a remote repository. Will be used to push a built image to.",
)
# TODO: this is only included for back compat. But we should remove this in the future
@click.option(
    "--project-queue",
    "-pq",
    default=None,
    hidden=True,
    help="Name of the project containing the queue to push to. If none, defaults to entity level queues.",
)
@click.option(
    "--dockerfile",
    "-D",
    default=None,
    help="Path to the Dockerfile used to build the job, relative to the job's root",
)
@click.option(
    "--priority",
    "-P",
    default=None,
    type=click.Choice(["critical", "high", "medium", "low"]),
    help="""When --queue is passed, set the priority of the job. Launch jobs with higher priority
    are served first.  The order, from highest to lowest priority, is: critical, high, medium, low""",
)
@display_error
def launch(
    uri,
    job,
    entry_point,
    git_version,
    build_context,
    name,
    resource,
    entity,
    project,
    docker_image,
    base_image,
    config,
    cli_template_vars,
    queue,
    run_async,
    resource_args,
    build,
    repository,
    project_queue,
    dockerfile,
    priority,
    job_name,
):
    """Start a W&B run from the given URI.

    The URI can bea wandb URI, a GitHub repo uri, or a local path). In the case of a
    wandb URI the arguments used in the original run will be used by default. These
    arguments can be overridden using the args option, or specifying those arguments in
    the config's 'overrides' key, 'args' field as a list of strings.

    Running `wandb launch [URI]` will launch the run directly. To add the run to a
    queue, run `wandb launch [URI] --queue [optional queuename]`.
    """
    logger.info(
        f"=== Launch called with kwargs {locals()} CLI Version: {wandb.__version__}==="
    )
    from wandb.sdk.launch._launch import _launch
    from wandb.sdk.launch.create_job import _create_job
    from wandb.sdk.launch.utils import _is_git_uri

    api = _get_cling_api()
    wandb._sentry.configure_scope(process_context="launch_cli")

    if run_async and queue is not None:
        raise LaunchError(
            "Cannot use both --async and --queue with wandb launch, see help for details."
        )

    if queue and docker_image and not project:
        raise LaunchError(
            "Cannot use --queue and --docker together without a project. Please specify a project with --project or -p."
        )

    if priority is not None and queue is None:
        raise LaunchError("--priority flag requires --queue to be set")

    if resource_args is not None:
        resource_args = util.load_json_yaml_dict(resource_args)
        if resource_args is None:
            raise LaunchError("Invalid format for resource-args")
    else:
        resource_args = {}

    if entry_point is not None:
        entry_point = shlex.split(entry_point)

    if config is not None:
        config = util.load_json_yaml_dict(config)
        if config is None:
            raise LaunchError("Invalid format for config")
    else:
        config = {}

    resource = resource or config.get("resource")

    if build and queue is None:
        raise LaunchError("Build flag requires a queue to be set")

    try:
        launch_utils.check_logged_in(api)
    except Exception:
        wandb.termerror(f"Error running job: {traceback.format_exc()}")

    run_id = config.get("run_id")

    # If URI was provided, we need to create a job from it.
    if uri:
        if entry_point is None:
            raise LaunchError(
                "Cannot provide a uri without an entry point. Please provide an "
                "entry point with --entry-point or -E."
            )
        if job is not None:
            raise LaunchError("Cannot provide both a uri and a job name.")
        job_type = (
            "git" if _is_git_uri(uri) else "code"
        )  # TODO: Add support for local URIs with git.
        if entity is None:
            entity = launch_utils.get_default_entity(api, config)
        artifact, _, _ = _create_job(
            api,
            job_type,
            uri,
            entrypoint=" ".join(entry_point),
            git_hash=git_version,
            name=job_name,
            project=project,
            base_image=base_image,
            build_context=build_context,
            dockerfile=dockerfile,
            entity=entity,
        )
        if artifact is None:
            raise LaunchError(f"Failed to create job from uri: {uri}")
        job = f"{entity}/{project}/{artifact.name}"

    if dockerfile:
        if "overrides" in config:
            config["overrides"]["dockerfile"] = dockerfile
        else:
            config["overrides"] = {"dockerfile": dockerfile}

    if priority is not None:
        priority_map = {
            "critical": 0,
            "high": 1,
            "medium": 2,
            "low": 3,
        }
        priority = priority_map[priority.lower()]

    template_variables = None
    if cli_template_vars:
        if queue is None:
            raise LaunchError("'--set-var' flag requires queue to be set")
        if entity is None:
            entity = launch_utils.get_default_entity(api, config)
        public_api = PublicApi()
        runqueue = RunQueue(client=public_api.client, name=queue, entity=entity)
        template_variables = launch_utils.fetch_and_validate_template_variables(
            runqueue, cli_template_vars
        )

    if queue is None:
        # direct launch
        try:
            run = asyncio.run(
                _launch(
                    api,
                    job,
                    project=project,
                    entity=entity,
                    docker_image=docker_image,
                    name=name,
                    entry_point=entry_point,
                    version=git_version,
                    resource=resource,
                    resource_args=resource_args,
                    launch_config=config,
                    synchronous=(not run_async),
                    run_id=run_id,
                    repository=repository,
                )
            )
            if asyncio.run(run.get_status()).state in [
                "failed",
                "stopped",
                "preempted",
            ]:
                wandb.termerror("Launched run exited with non-zero status")
                sys.exit(1)
        except LaunchError as e:
            logger.error("=== %s ===", e)
            wandb._sentry.exception(e)
            sys.exit(e)
        except ExecutionError as e:
            logger.error("=== %s ===", e)
            wandb._sentry.exception(e)
            sys.exit(e)
        except asyncio.CancelledError:
            sys.exit(0)
    else:
        try:
            _launch_add(
                api,
                job,
                config,
                template_variables,
                project,
                entity,
                queue,
                resource,
                entry_point,
                name,
                git_version,
                docker_image,
                project_queue,
                resource_args,
                build=build,
                run_id=run_id,
                repository=repository,
                priority=priority,
            )

        except Exception as e:
            wandb._sentry.exception(e)
            raise e


@cli.command(
    context_settings=CONTEXT,
    help="Run a W&B launch agent.",
)
@click.pass_context
@click.option(
    "--queue",
    "-q",
    "queues",
    default=None,
    multiple=True,
    metavar="<queue(s)>",
    help="The name of a queue for the agent to watch. Multiple -q flags supported.",
)
@click.option(
    "--entity",
    "-e",
    default=None,
    help="The entity to use. Defaults to current logged-in user",
)
@click.option(
    "--log-file",
    "-l",
    default=None,
    help=(
        "Destination for internal agent logs. Use - for stdout. "
        "By default all agents logs will go to debug.log in your wandb/ "
        "subdirectory or WANDB_DIR if set."
    ),
)
@click.option(
    "--max-jobs",
    "-j",
    default=None,
    help="The maximum number of launch jobs this agent can run in parallel. Defaults to 1. Set to -1 for no upper limit",
)
@click.option(
    "--config", "-c", default=None, help="path to the agent config yaml to use"
)
@click.option(
    "--url",
    "-u",
    default=None,
    hidden=True,
    help="a wandb client registration URL, this is generated in the UI",
)
@click.option("--verbose", "-v", count=True, help="Display verbose output")
@display_error
def launch_agent(
    ctx,
    entity=None,
    queues=None,
    max_jobs=None,
    config=None,
    url=None,
    log_file=None,
    verbose=0,
):
    logger.info(
        f"=== Launch-agent called with kwargs {locals()}  CLI Version: {wandb.__version__} ==="
    )
    if url is not None:
        raise LaunchError(
            "--url is not supported in this version, upgrade with: pip install -u wandb"
        )

    import wandb.sdk.launch._launch as _launch

    if log_file is not None:
        _launch.set_launch_logfile(log_file)

    api = _get_cling_api()
    wandb._sentry.configure_scope(process_context="launch_agent")
    agent_config, api = _launch.resolve_agent_config(
        entity, max_jobs, queues, config, verbose
    )

    if len(agent_config.get("queues")) == 0:
        raise LaunchError(
            "To launch an agent please specify a queue or a list of queues in the configuration file or cli."
        )

    launch_utils.check_logged_in(api)

    wandb.termlog("Starting launch agent ✨")
    try:
        _launch.create_and_run_agent(api, agent_config)
    except Exception as e:
        wandb._sentry.exception(e)
        raise e


@cli.command(context_settings=CONTEXT, help="Run the W&B agent")
@click.pass_context
@click.option(
    "--project",
    "-p",
    default=None,
    help="""The name of the project where W&B runs created from the sweep are sent to. If the project is not specified, the run is sent to a project labeled 'Uncategorized'.""",
)
@click.option(
    "--entity",
    "-e",
    default=None,
    help="""The username or team name where you want to send W&B runs created by the sweep to. Ensure that the entity you specify already exists. If you don't specify an entity, the run will be sent to your default entity, which is usually your username.""",
)
@click.option(
    "--count", default=None, type=int, help="The max number of runs for this agent."
)
@click.argument("sweep_id")
@display_error
def agent(ctx, project, entity, count, sweep_id):
    api = _get_cling_api()
    if not api.is_authenticated:
        wandb.termlog("Login to W&B to use the sweep agent feature")
        ctx.invoke(login, no_offline=True)
        api = _get_cling_api(reset=True)

    wandb.termlog("Starting wandb agent 🕵️")
    wandb_agent.agent(sweep_id, entity=entity, project=project, count=count)

    # you can send local commands like so:
    # agent_api.command({'type': 'run', 'program': 'train.py',
    #                'args': ['--max_epochs=10']})


@cli.command(
    context_settings=RUN_CONTEXT, help="Run a W&B launch sweep scheduler (Experimental)"
)
@click.pass_context
@click.argument("sweep_id")
@display_error
def scheduler(
    ctx,
    sweep_id,
):
    api = InternalApi()
    if not api.is_authenticated:
        wandb.termlog("Login to W&B to use the sweep scheduler feature")
        ctx.invoke(login, no_offline=True)
        api = InternalApi(reset=True)

    wandb._sentry.configure_scope(process_context="sweep_scheduler")
    wandb.termlog("Starting a Launch Scheduler 🚀")
    from wandb.sdk.launch.sweeps import load_scheduler

    # TODO(gst): remove this monstrosity
    # Future-proofing hack to pull any kwargs that get passed in through the CLI
    kwargs = {}
    for i, _arg in enumerate(ctx.args):
        if isinstance(_arg, str) and _arg.startswith("--"):
            # convert input kwargs from hyphens to underscores
            _key = _arg[2:].replace("-", "_")
            _args = ctx.args[i + 1]
            if str.isdigit(_args):
                _args = int(_args)
            kwargs[_key] = _args
    try:
        sweep_type = kwargs.get("sweep_type", "wandb")
        _scheduler = load_scheduler(scheduler_type=sweep_type)(
            api,
            sweep_id=sweep_id,
            **kwargs,
        )
        _scheduler.start()
    except Exception as e:
        wandb._sentry.exception(e)
        raise e


@cli.group(help="Commands for managing and viewing W&B jobs")
def job() -> None:
    pass


@job.command("list", help="List jobs in a project")
@click.option(
    "--project",
    "-p",
    envvar=env.PROJECT,
    help="The project you want to list jobs from.",
)
@click.option(
    "--entity",
    "-e",
    default="models",
    envvar=env.ENTITY,
    help="The entity the jobs belong to",
)
def _list(project, entity):
    wandb.termlog(f"Listing jobs in {entity}/{project}")
    public_api = PublicApi()
    try:
        jobs = public_api.list_jobs(entity=entity, project=project)
    except wandb.errors.CommError as e:
        wandb.termerror(f"{e}")
        return

    if len(jobs) == 0:
        wandb.termlog("No jobs found")
        return

    for job in jobs:
        aliases = []
        if len(job["edges"]) == 0:
            # deleted?
            continue

        name = job["edges"][0]["node"]["artifactSequence"]["name"]
        for version in job["edges"]:
            aliases += [x["alias"] for x in version["node"]["aliases"]]

        # only list the most recent 10 job versions
        aliases_str = ",".join(aliases[::-1])
        wandb.termlog(f"{name} -- versions ({len(aliases)}): {aliases_str}")


@job.command(
    help="Describe a launch job. Provide the launch job in the form of: entity/project/job-name:alias-or-version"
)
@click.argument("job")
def describe(job):
    public_api = PublicApi()
    try:
        job = public_api.job(name=job)
    except wandb.errors.CommError as e:
        wandb.termerror(f"{e}")
        return

    for key in job._job_info:
        if key.startswith("_"):
            continue
        wandb.termlog(f"{key}: {job._job_info[key]}")


@job.command(
    no_args_is_help=True,
)
@click.option(
    "--project",
    "-p",
    envvar=env.PROJECT,
    help="The project you want to list jobs from.",
)
@click.option(
    "--entity",
    "-e",
    envvar=env.ENTITY,
    help="The entity the jobs belong to",
)
@click.option(
    "--name",
    "-n",
    help="Name for the job",
)
@click.option(
    "--description",
    "-d",
    help="Description for the job",
)
@click.option(
    "--alias",
    "-a",
    "aliases",
    help="Alias for the job",
    multiple=True,
    default=tuple(),
)
@click.option(
    "--entry-point",
    "-E",
    "entrypoint",
    help="Entrypoint to the script, including an executable and an entrypoint "
    "file. Required for code or repo jobs. If --build-context is provided, "
    "paths in the entrypoint command will be relative to the build context.",
)
@click.option(
    "--git-hash",
    "-g",
    "git_hash",
    type=str,
    help="Commit reference to use as the source for git jobs",
)
@click.option(
    "--runtime",
    "-r",
    type=str,
    help="Python runtime to execute the job",
)
@click.option(
    "--build-context",
    "-b",
    type=str,
    help="Path to the build context from the root of the job source code. If "
    "provided, this is used as the base path for the Dockerfile and entrypoint.",
)
@click.option(
    "--base-image",
    "-B",
    type=str,
    help="Base image to use for the job. Incompatible with image jobs.",
)
@click.option(
    "--dockerfile",
    "-D",
    type=str,
    help="Path to the Dockerfile for the job. If --build-context is provided, "
    "the Dockerfile path will be relative to the build context.",
)
@click.argument(
    "job_type",
    type=click.Choice(("git", "code", "image")),
)
@click.argument("path")
def create(
    path,
    project,
    entity,
    name,
    job_type,
    description,
    aliases,
    entrypoint,
    git_hash,
    runtime,
    build_context,
    base_image,
    dockerfile,
):
    """Create a job from a source, without a wandb run.

    Jobs can be of three types, git, code, or image.

    git: A git source, with an entrypoint either in the path or provided explicitly pointing to the main python executable.
    code: A code path, containing a requirements.txt file.
    image: A docker image.
    """
    from wandb.sdk.launch.create_job import _create_job

    api = _get_cling_api()
    wandb._sentry.configure_scope(process_context="job_create")

    entity = entity or os.getenv("WANDB_ENTITY") or api.default_entity
    if not entity:
        wandb.termerror("No entity provided, use --entity or set WANDB_ENTITY")
        return

    project = project or os.getenv("WANDB_PROJECT")
    if not project:
        wandb.termerror("No project provided, use --project or set WANDB_PROJECT")
        return

    if entrypoint is None and job_type in ["git", "code"]:
        wandb.termwarn(
            f"No entrypoint provided for {job_type} job, defaulting to main.py"
        )
        entrypoint = "main.py"

    if job_type == "image" and base_image:
        wandb.termerror("Cannot provide --base-image/-B for an `image` job")
        return

    artifact, action, aliases = _create_job(
        api=api,
        path=path,
        entity=entity,
        project=project,
        name=name,
        job_type=job_type,
        description=description,
        aliases=list(aliases),
        entrypoint=entrypoint,
        git_hash=git_hash,
        runtime=runtime,
        build_context=build_context,
        base_image=base_image,
        dockerfile=dockerfile,
    )
    if not artifact:
        wandb.termerror("Job creation failed")
        return

    artifact_path = f"{entity}/{project}/{artifact.name}"
    msg = f"{action} job: {click.style(artifact_path, fg='yellow')}"
    if len(aliases) == 1:
        alias_str = click.style(aliases[0], fg="yellow")
        msg += f", with alias: {alias_str}"
    elif len(aliases) > 1:
        alias_str = click.style(", ".join(aliases), fg="yellow")
        msg += f", with aliases: {alias_str}"

    wandb.termlog(msg)
    web_url = util.app_url(api.settings().get("base_url"))
    url = click.style(f"{web_url}/{entity}/{project}/jobs", underline=True)
    wandb.termlog(f"View all jobs in project '{project}' here: {url}\n")


@cli.command(context_settings=CONTEXT, help="Run the W&B local sweep controller")
@click.option("--verbose", is_flag=True, default=False, help="Display verbose output")
@click.argument("sweep_id")
@display_error
def controller(verbose, sweep_id):
    click.echo("Starting wandb controller...")
    from wandb import controller as wandb_controller

    tuner = wandb_controller(sweep_id)
    tuner.run(verbose=verbose)


@cli.command(context_settings=RUN_CONTEXT, name="docker-run")
@click.pass_context
@click.argument("docker_run_args", nargs=-1)
def docker_run(ctx, docker_run_args):
    """Wrap `docker run` and adds WANDB_API_KEY and WANDB_DOCKER environment variables.

    This will also set the runtime to nvidia if the nvidia-docker executable is present
    on the system and --runtime wasn't set.

    See `docker run --help` for more details.
    """
    api = InternalApi()
    args = list(docker_run_args)
    if len(args) > 0 and args[0] == "run":
        args.pop(0)
    if len([a for a in args if a.startswith("--runtime")]) == 0 and find_executable(
        "nvidia-docker"
    ):
        args = ["--runtime", "nvidia"] + args
    #  TODO: image_from_docker_args uses heuristics to find the docker image arg, there are likely cases
    #  where this won't work
    image = util.image_from_docker_args(args)
    resolved_image = None
    if image:
        resolved_image = wandb.docker.image_id(image)
    if resolved_image:
        args = ["-e", "WANDB_DOCKER={}".format(resolved_image)] + args
    else:
        wandb.termlog(
            "Couldn't detect image argument, running command without the WANDB_DOCKER env variable"
        )
    if api.api_key:
        args = ["-e", "WANDB_API_KEY={}".format(api.api_key)] + args
    else:
        wandb.termlog(
            "Not logged in, run `wandb login` from the host machine to enable result logging"
        )
    subprocess.call(["docker", "run"] + args)


@cli.command(context_settings=RUN_CONTEXT)
@click.pass_context
@click.argument("docker_run_args", nargs=-1)
@click.argument("docker_image", required=False)
@click.option(
    "--nvidia/--no-nvidia",
    default=find_executable("nvidia-docker") is not None,
    help="Use the nvidia runtime, defaults to nvidia if nvidia-docker is present",
)
@click.option(
    "--digest", is_flag=True, default=False, help="Output the image digest and exit"
)
@click.option(
    "--jupyter/--no-jupyter", default=False, help="Run jupyter lab in the container"
)
@click.option(
    "--dir", default="/app", help="Which directory to mount the code in the container"
)
@click.option("--no-dir", is_flag=True, help="Don't mount the current directory")
@click.option(
    "--shell", default="/bin/bash", help="The shell to start the container with"
)
@click.option("--port", default="8888", help="The host port to bind jupyter on")
@click.option("--cmd", help="The command to run in the container")
@click.option(
    "--no-tty", is_flag=True, default=False, help="Run the command without a tty"
)
@display_error
def docker(
    ctx,
    docker_run_args,
    docker_image,
    nvidia,
    digest,
    jupyter,
    dir,
    no_dir,
    shell,
    port,
    cmd,
    no_tty,
):
    """Run your code in a docker container.

    W&B docker lets you run your code in a docker image ensuring wandb is configured. It
    adds the WANDB_DOCKER and WANDB_API_KEY environment variables to your container and
    mounts the current directory in /app by default.  You can pass additional args which
    will be added to `docker run` before the image name is declared, we'll choose a
    default image for you if one isn't passed:

    ```sh
    wandb docker -v /mnt/dataset:/app/data
    wandb docker gcr.io/kubeflow-images-public/tensorflow-1.12.0-notebook-cpu:v0.4.0 --jupyter
    wandb docker wandb/deepo:keras-gpu --no-tty --cmd "python train.py --epochs=5"
    ```

    By default, we override the entrypoint to check for the existence of wandb and
    install it if not present.  If you pass the --jupyter flag we will ensure jupyter is
    installed and start jupyter lab on port 8888.  If we detect nvidia-docker on your
    system we will use the nvidia runtime.  If you just want wandb to set environment
    variable to an existing docker run command, see the wandb docker-run command.
    """
    api = InternalApi()
    if not find_executable("docker"):
        raise ClickException("Docker not installed, install it from https://docker.com")
    args = list(docker_run_args)
    image = docker_image or ""
    # remove run for users used to nvidia-docker
    if len(args) > 0 and args[0] == "run":
        args.pop(0)
    if image == "" and len(args) > 0:
        image = args.pop(0)
    # If the user adds docker args without specifying an image (should be rare)
    if not util.docker_image_regex(image.split("@")[0]):
        if image:
            args = args + [image]
        image = wandb.docker.default_image(gpu=nvidia)
        subprocess.call(["docker", "pull", image])
    _, repo_name, tag = wandb.docker.parse(image)

    resolved_image = wandb.docker.image_id(image)
    if resolved_image is None:
        raise ClickException(
            "Couldn't find image locally or in a registry, try running `docker pull {}`".format(
                image
            )
        )
    if digest:
        sys.stdout.write(resolved_image)
        exit(0)

    existing = wandb.docker.shell(
        ["ps", "-f", "ancestor={}".format(resolved_image), "-q"]
    )
    if existing:
        if click.confirm(
            "Found running container with the same image, do you want to attach?"
        ):
            subprocess.call(["docker", "attach", existing.split("\n")[0]])
            exit(0)
    cwd = os.getcwd()
    command = [
        "docker",
        "run",
        "-e",
        "LANG=C.UTF-8",
        "-e",
        "WANDB_DOCKER={}".format(resolved_image),
        "--ipc=host",
        "-v",
        wandb.docker.entrypoint + ":/wandb-entrypoint.sh",
        "--entrypoint",
        "/wandb-entrypoint.sh",
    ]
    if nvidia:
        command.extend(["--runtime", "nvidia"])
    if not no_dir:
        #  TODO: We should default to the working directory if defined
        command.extend(["-v", cwd + ":" + dir, "-w", dir])
    if api.api_key:
        command.extend(["-e", "WANDB_API_KEY={}".format(api.api_key)])
    else:
        wandb.termlog(
            "Couldn't find WANDB_API_KEY, run `wandb login` to enable streaming metrics"
        )
    if jupyter:
        command.extend(["-e", "WANDB_ENSURE_JUPYTER=1", "-p", port + ":8888"])
        no_tty = True
        cmd = "jupyter lab --no-browser --ip=0.0.0.0 --allow-root --NotebookApp.token= --notebook-dir {}".format(
            dir
        )
    command.extend(args)
    if no_tty:
        command.extend([image, shell, "-c", cmd])
    else:
        if cmd:
            command.extend(["-e", "WANDB_COMMAND={}".format(cmd)])
        command.extend(["-it", image, shell])
        wandb.termlog("Launching docker container \U0001f6a2")
    subprocess.call(command)


@cli.command(
    context_settings=RUN_CONTEXT,
    help="Start a local W&B container (deprecated, see wandb server --help)",
    hidden=True,
)
@click.pass_context
@click.option("--port", "-p", default="8080", help="The host port to bind W&B local on")
@click.option(
    "--env", "-e", default=[], multiple=True, help="Env vars to pass to wandb/local"
)
@click.option(
    "--daemon/--no-daemon", default=True, help="Run or don't run in daemon mode"
)
@click.option(
    "--upgrade", is_flag=True, default=False, help="Upgrade to the most recent version"
)
@click.option(
    "--edge", is_flag=True, default=False, help="Run the bleeding edge", hidden=True
)
@display_error
def local(ctx, *args, **kwargs):
    wandb.termwarn("`wandb local` has been replaced with `wandb server start`.")
    ctx.invoke(start, *args, **kwargs)


@cli.group(help="Commands for operating a local W&B server")
def server():
    pass


@server.command(context_settings=RUN_CONTEXT, help="Start a local W&B server")
@click.pass_context
@click.option(
    "--port", "-p", default="8080", help="The host port to bind W&B server on"
)
@click.option(
    "--env", "-e", default=[], multiple=True, help="Env vars to pass to wandb/local"
)
@click.option(
    "--daemon/--no-daemon", default=True, help="Run or don't run in daemon mode"
)
@click.option(
    "--upgrade",
    is_flag=True,
    default=False,
    help="Upgrade to the most recent version",
    hidden=True,
)
@click.option(
    "--edge", is_flag=True, default=False, help="Run the bleeding edge", hidden=True
)
@display_error
def start(ctx, port, env, daemon, upgrade, edge):
    api = InternalApi()
    if not find_executable("docker"):
        raise ClickException("Docker not installed, install it from https://docker.com")
    local_image_sha = wandb.docker.image_id("wandb/local").split("wandb/local")[-1]
    registry_image_sha = wandb.docker.image_id_from_registry("wandb/local").split(
        "wandb/local"
    )[-1]
    if local_image_sha != registry_image_sha:
        if upgrade:
            subprocess.call(["docker", "pull", "wandb/local"])
        else:
            wandb.termlog(
                "A new version of the W&B server is available, upgrade by calling `wandb server start --upgrade`"
            )
    running = subprocess.check_output(
        ["docker", "ps", "--filter", "name=wandb-local", "--format", "{{.ID}}"]
    )
    if running != b"":
        if upgrade:
            subprocess.call(["docker", "stop", "wandb-local"])
        else:
            wandb.termerror(
                "A container named wandb-local is already running, run `docker stop wandb-local` if you want to start a new instance"
            )
            exit(1)
    image = "docker.pkg.github.com/wandb/core/local" if edge else "wandb/local"
    username = getpass.getuser()
    env_vars = ["-e", "LOCAL_USERNAME={}".format(username)]
    for e in env:
        env_vars.append("-e")
        env_vars.append(e)
    command = [
        "docker",
        "run",
        "--rm",
        "-v",
        "wandb:/vol",
        "-p",
        port + ":8080",
        "--name",
        "wandb-local",
    ] + env_vars
    host = f"http://localhost:{port}"
    api.set_setting("base_url", host, globally=True, persist=True)
    if daemon:
        command += ["-d"]
    command += [image]

    # DEVNULL is only in py3
    try:
        from subprocess import DEVNULL
    except ImportError:
        DEVNULL = open(os.devnull, "wb")  # noqa: N806
    code = subprocess.call(command, stdout=DEVNULL)
    if daemon:
        if code != 0:
            wandb.termerror(
                "Failed to launch the W&B server container, see the above error."
            )
            exit(1)
        else:
            wandb.termlog(
                "W&B server started at http://localhost:{} \U0001f680".format(port)
            )
            wandb.termlog("You can stop the server by running `wandb server stop`")
            if not api.api_key:
                # Let the server start before potentially launching a browser
                time.sleep(2)
                ctx.invoke(login, host=host)


@server.command(context_settings=RUN_CONTEXT, help="Stop a local W&B server")
def stop():
    if not find_executable("docker"):
        raise ClickException("Docker not installed, install it from https://docker.com")
    subprocess.call(["docker", "stop", "wandb-local"])


@cli.group(help="Commands for interacting with artifacts")
def artifact():
    pass


@artifact.command(context_settings=CONTEXT, help="Upload an artifact to wandb")
@click.argument("path")
@click.option(
    "--name", "-n", help="The name of the artifact to push: project/artifact_name"
)
@click.option("--description", "-d", help="A description of this artifact")
@click.option("--type", "-t", default="dataset", help="The type of the artifact")
@click.option(
    "--alias",
    "-a",
    default=["latest"],
    multiple=True,
    help="An alias to apply to this artifact",
)
@click.option("--id", "run_id", help="The run you want to upload to.")
@click.option(
    "--resume",
    is_flag=True,
    default=None,
    help="Resume the last run from your current directory.",
)
@click.option(
    "--skip_cache",
    is_flag=True,
    default=False,
    help="Skip caching while uploading artifact files.",
)
@click.option(
    "--policy",
    default="mutable",
    type=click.Choice(["mutable", "immutable"]),
    help="Set the storage policy while uploading artifact files.",
)
@display_error
def put(
    path,
    name,
    description,
    type,
    alias,
    run_id,
    resume,
    skip_cache,
    policy,
):
    if name is None:
        name = os.path.basename(path)
    public_api = PublicApi()
    entity, project, artifact_name = public_api._parse_artifact_path(name)
    if project is None:
        project = click.prompt("Enter the name of the project you want to use")
    # TODO: settings nightmare...
    api = InternalApi()
    api.set_setting("entity", entity)
    api.set_setting("project", project)
    artifact = wandb.Artifact(name=artifact_name, type=type, description=description)
    artifact_path = f"{entity}/{project}/{artifact_name}:{alias[0]}"
    if os.path.isdir(path):
        wandb.termlog(f'Uploading directory {path} to: "{artifact_path}" ({type})')
        artifact.add_dir(path, skip_cache=skip_cache, policy=policy)
    elif os.path.isfile(path):
        wandb.termlog(f'Uploading file {path} to: "{artifact_path}" ({type})')
        artifact.add_file(path, skip_cache=skip_cache, policy=policy)
    elif "://" in path:
        wandb.termlog(
            f'Logging reference artifact from {path} to: "{artifact_path}" ({type})'
        )
        artifact.add_reference(path)
    else:
        raise ClickException("Path argument must be a file or directory")

    with wandb.init(
        entity=entity,
        project=project,
        config={"path": path},
        job_type="cli_put",
        id=run_id,
        resume=resume,
    ) as run:
        run.log_artifact(artifact, aliases=alias)
    artifact.wait()

    wandb.termlog(
        "Artifact uploaded, use this artifact in a run by adding:\n", prefix=False
    )
    wandb.termlog(
        f'    artifact = run.use_artifact("{artifact.source_qualified_name}")\n',
        prefix=False,
    )


@artifact.command(context_settings=CONTEXT, help="Download an artifact from wandb")
@click.argument("path")
@click.option("--root", help="The directory you want to download the artifact to")
@click.option("--type", help="The type of artifact you are downloading")
@display_error
def get(path, root, type):
    public_api = PublicApi()
    entity, project, artifact_name = public_api._parse_artifact_path(path)
    if project is None:
        project = click.prompt("Enter the name of the project you want to use")

    try:
        artifact_parts = artifact_name.split(":")
        if len(artifact_parts) > 1:
            version = artifact_parts[1]
            artifact_name = artifact_parts[0]
        else:
            version = "latest"
        full_path = f"{entity}/{project}/{artifact_name}:{version}"
        wandb.termlog(
            "Downloading {type} artifact {full_path}".format(
                type=type or "dataset", full_path=full_path
            )
        )
        artifact = public_api.artifact(full_path, type=type)
        path = artifact.download(root=root)
        wandb.termlog("Artifact downloaded to {}".format(path))
    except ValueError:
        raise ClickException("Unable to download artifact")


@artifact.command(
    context_settings=CONTEXT, help="List all artifacts in a wandb project"
)
@click.argument("path")
@click.option("--type", "-t", help="The type of artifacts to list")
@display_error
def ls(path, type):
    public_api = PublicApi()
    if type is not None:
        types = [public_api.artifact_type(type, path)]
    else:
        types = public_api.artifact_types(path)

    for kind in types:
        for collection in kind.collections():
            versions = public_api.artifact_versions(
                kind.type,
                "/".join([kind.entity, kind.project, collection.name]),
                per_page=1,
            )
            latest = next(versions)
            print(
                "{:<15s}{:<15s}{:>15s} {:<20s}".format(
                    kind.type,
                    latest.updated_at,
                    util.to_human_size(latest.size),
                    latest.name,
                )
            )


@artifact.group(help="Commands for interacting with the artifact cache")
def cache():
    pass


@cache.command(
    context_settings=CONTEXT,
    help="Clean up less frequently used files from the artifacts cache",
)
@click.argument("target_size")
@click.option("--remove-temp/--no-remove-temp", default=False, help="Remove temp files")
@display_error
def cleanup(target_size, remove_temp):
    target_size = util.from_human_size(target_size)
    cache = get_artifact_file_cache()
    reclaimed_bytes = cache.cleanup(target_size, remove_temp)
    print(f"Reclaimed {util.to_human_size(reclaimed_bytes)} of space")


@cli.command(context_settings=CONTEXT, help="Pull files from Weights & Biases")
@click.argument("run", envvar=env.RUN_ID)
@click.option(
    "--project", "-p", envvar=env.PROJECT, help="The project you want to download."
)
@click.option(
    "--entity",
    "-e",
    default="models",
    envvar=env.ENTITY,
    help="The entity to scope the listing to.",
)
@display_error
def pull(run, project, entity):
    api = InternalApi()
    project, run = api.parse_slug(run, project=project)
    urls = api.download_urls(project, run=run, entity=entity)
    if len(urls) == 0:
        raise ClickException("Run has no files")
    click.echo(f"Downloading: {click.style(project, bold=True)}/{run}")

    for name in urls:
        if api.file_current(name, urls[name]["md5"]):
            click.echo("File {} is up to date".format(name))
        else:
            length, response = api.download_file(urls[name]["url"])
            # TODO: I had to add this because some versions in CI broke click.progressbar
            sys.stdout.write("File {}\r".format(name))
            dirname = os.path.dirname(name)
            if dirname != "":
                filesystem.mkdir_exists_ok(dirname)
            with click.progressbar(
                length=length,
                label="File {}".format(name),
                fill_char=click.style("&", fg="green"),
            ) as bar:
                with open(name, "wb") as f:
                    for data in response.iter_content(chunk_size=4096):
                        f.write(data)
                        bar.update(len(data))


@cli.command(
    context_settings=CONTEXT, help="Restore code, config and docker state for a run"
)
@click.pass_context
@click.argument("run", envvar=env.RUN_ID)
@click.option("--no-git", is_flag=True, default=False, help="Don't restore git state")
@click.option(
    "--branch/--no-branch",
    default=True,
    help="Whether to create a branch or checkout detached",
)
@click.option(
    "--project", "-p", envvar=env.PROJECT, help="The project you wish to upload to."
)
@click.option(
    "--entity", "-e", envvar=env.ENTITY, help="The entity to scope the listing to."
)
@display_error
def restore(ctx, run, no_git, branch, project, entity):
    from wandb.old.core import wandb_dir

    api = _get_cling_api()
    if ":" in run:
        if "/" in run:
            entity, rest = run.split("/", 1)
        else:
            rest = run
        project, run = rest.split(":", 1)
    elif run.count("/") > 1:
        entity, run = run.split("/", 1)

    project, run = api.parse_slug(run, project=project)
    commit, json_config, patch_content, metadata = api.run_config(
        project, run=run, entity=entity
    )
    repo = metadata.get("git", {}).get("repo")
    image = metadata.get("docker")
    restore_message = """`wandb restore` needs to be run from the same git repository as the original run.
Run `git clone {}` and restore from there or pass the --no-git flag.""".format(repo)
    if no_git:
        commit = None
    elif not api.git.enabled:
        if repo:
            raise ClickException(restore_message)
        elif image:
            wandb.termlog(
                "Original run has no git history.  Just restoring config and docker"
            )

    if commit and api.git.enabled:
        wandb.termlog(f"Fetching origin and finding commit: {commit}")
        subprocess.check_call(["git", "fetch", "--all"])
        try:
            api.git.repo.commit(commit)
        except ValueError:
            wandb.termlog(f"Couldn't find original commit: {commit}")
            commit = None
            files = api.download_urls(project, run=run, entity=entity)
            for filename in files:
                if filename.startswith("upstream_diff_") and filename.endswith(
                    ".patch"
                ):
                    commit = filename[len("upstream_diff_") : -len(".patch")]
                    try:
                        api.git.repo.commit(commit)
                    except ValueError:
                        commit = None
                    else:
                        break

            if commit:
                wandb.termlog(f"Falling back to upstream commit: {commit}")
                patch_path, _ = api.download_write_file(files[filename])
            else:
                raise ClickException(restore_message)
        else:
            if patch_content:
                patch_path = os.path.join(wandb_dir(), "diff.patch")
                with open(patch_path, "w") as f:
                    f.write(patch_content)
            else:
                patch_path = None

        branch_name = "wandb/{}".format(run)
        if branch and branch_name not in api.git.repo.branches:
            api.git.repo.git.checkout(commit, b=branch_name)
            wandb.termlog(
                "Created branch {}".format(click.style(branch_name, bold=True))
            )
        elif branch:
            wandb.termlog(
                "Using existing branch, run `git branch -D {}` from master for a clean checkout".format(
                    branch_name
                )
            )
            api.git.repo.git.checkout(branch_name)
        else:
            wandb.termlog("Checking out {} in detached mode".format(commit))
            api.git.repo.git.checkout(commit)

        if patch_path:
            # we apply the patch from the repository root so git doesn't exclude
            # things outside the current directory
            root = api.git.root
            patch_rel_path = os.path.relpath(patch_path, start=root)
            # --reject is necessary or else this fails any time a binary file
            # occurs in the diff
            exit_code = subprocess.call(
                ["git", "apply", "--reject", patch_rel_path], cwd=root
            )
            if exit_code == 0:
                wandb.termlog("Applied patch")
            else:
                wandb.termerror(
                    "Failed to apply patch, try un-staging any un-committed changes"
                )

    filesystem.mkdir_exists_ok(wandb_dir())
    config_path = os.path.join(wandb_dir(), "config.yaml")
    config = Config()
    for k, v in json_config.items():
        if k not in ("_wandb", "wandb_version"):
            config[k] = v
    s = b"wandb_version: 1"
    s += b"\n\n" + yaml.dump(
        config._as_dict(),
        Dumper=yaml.SafeDumper,
        default_flow_style=False,
        allow_unicode=True,
        encoding="utf-8",
    )
    s = s.decode("utf-8")
    with open(config_path, "w") as f:
        f.write(s)

    wandb.termlog("Restored config variables to {}".format(config_path))
    if image:
        if not metadata["program"].startswith("<") and metadata.get("args") is not None:
            # TODO: we may not want to default to python here.
            runner = util.find_runner(metadata["program"]) or ["python"]
            command = runner + [metadata["program"]] + metadata["args"]
            cmd = " ".join(command)
        else:
            wandb.termlog("Couldn't find original command, just restoring environment")
            cmd = None
        wandb.termlog("Docker image found, attempting to start")
        ctx.invoke(docker, docker_run_args=[image], cmd=cmd)

    return commit, json_config, patch_content, repo, metadata


@cli.command(context_settings=CONTEXT, help="Run any script with wandb", hidden=True)
@click.pass_context
@click.argument("program")
@click.argument("args", nargs=-1)
@display_error
def magic(ctx, program, args):
    def magic_run(cmd, globals, locals):
        try:
            exec(cmd, globals, locals)
        finally:
            pass

    sys.argv[:] = args
    sys.argv.insert(0, program)
    sys.path.insert(0, os.path.dirname(program))
    try:
        with open(program, "rb") as fp:
            code = compile(fp.read(), program, "exec")
    except OSError:
        click.echo(
            click.style("Could not launch program: {}".format(program), fg="red")
        )
        sys.exit(1)
    globs = {
        "__file__": program,
        "__name__": "__main__",
        "__package__": None,
        "wandb_magic_install": magic_install,
    }
    prep = """
import __main__
__main__.__file__ = "{}"
wandb_magic_install()
""".format(program)
    magic_run(prep, globs, None)
    magic_run(code, globs, None)


@cli.command("online", help="Enable W&B sync")
@display_error
def online():
    api = InternalApi()
    try:
        api.clear_setting("disabled", persist=True)
        api.clear_setting("mode", persist=True)
    except configparser.Error:
        pass
    click.echo(
        "W&B online. Running your script from this directory will now sync to the cloud."
    )


@cli.command("offline", help="Disable W&B sync")
@display_error
def offline():
    api = InternalApi()
    try:
        api.set_setting("disabled", "true", persist=True)
        api.set_setting("mode", "offline", persist=True)
        click.echo(
            "W&B offline. Running your script from this directory will only write metadata locally. Use wandb disabled to completely turn off W&B."
        )
    except configparser.Error:
        click.echo(
            "Unable to write config, copy and paste the following in your terminal to turn off W&B:\nexport WANDB_MODE=offline"
        )


@cli.command("on", hidden=True)
@click.pass_context
@display_error
def on(ctx):
    ctx.invoke(online)


@cli.command("off", hidden=True)
@click.pass_context
@display_error
def off(ctx):
    ctx.invoke(offline)


@cli.command("status", help="Show configuration settings")
@click.option(
    "--settings/--no-settings", help="Show the current settings", default=True
)
def status(settings):
    api = _get_cling_api()
    if settings:
        click.echo(click.style("Current Settings", bold=True))
        settings = api.settings()
        click.echo(
            json.dumps(settings, sort_keys=True, indent=2, separators=(",", ": "))
        )


@cli.command("disabled", help="Disable W&B.")
@click.option(
    "--service",
    is_flag=True,
    show_default=True,
    default=True,
    help="Disable W&B service",
)
def disabled(service):
    api = InternalApi()
    try:
        api.set_setting("mode", "disabled", persist=True)
        click.echo("W&B disabled.")
    except configparser.Error:
        click.echo(
            "Unable to write config, copy and paste the following in your terminal to turn off W&B:\nexport WANDB_MODE=disabled"
        )


@cli.command("enabled", help="Enable W&B.")
@click.option(
    "--service",
    is_flag=True,
    show_default=True,
    default=True,
    help="Enable W&B service",
)
def enabled(service):
    api = InternalApi()
    try:
        api.set_setting("mode", "online", persist=True)
        click.echo("W&B enabled.")
    except configparser.Error:
        click.echo(
            "Unable to write config, copy and paste the following in your terminal to turn on W&B:\nexport WANDB_MODE=online"
        )


@cli.command(context_settings=CONTEXT, help="Verify your local instance")
@click.option("--host", default=None, help="Test a specific instance of W&B")
def verify(host):
    # TODO: (kdg) Build this all into a WandbVerify object, and clean this up.
    os.environ["WANDB_SILENT"] = "true"
    os.environ["WANDB_PROJECT"] = "verify"
    api = _get_cling_api()
    reinit = False
    if host is None:
        host = api.settings("base_url")
        print(f"Default host selected: {host}")
    # if the given host does not match the default host, re-run init
    elif host != api.settings("base_url"):
        reinit = True

    tmp_dir = tempfile.mkdtemp()
    print(
        "Find detailed logs for this test at: {}".format(os.path.join(tmp_dir, "wandb"))
    )
    os.chdir(tmp_dir)
    os.environ["WANDB_BASE_URL"] = host
    wandb.login(host=host)
    if reinit:
        api = _get_cling_api(reset=True)
    if not wandb_verify.check_host(host):
        sys.exit(1)
    if not wandb_verify.check_logged_in(api, host):
        sys.exit(1)
    url_success, url = wandb_verify.check_graphql_put(api, host)
    large_post_success = wandb_verify.check_large_post()
    wandb_verify.check_secure_requests(
        api.settings("base_url"),
        "Checking requests to base url",
        "Connections are not made over https. SSL required for secure communications.",
    )
    if url:
        wandb_verify.check_secure_requests(
            url,
            "Checking requests made over signed URLs",
            "Signed URL requests not made over https. SSL is required for secure communications.",
        )
        wandb_verify.check_cors_configuration(url, host)
    wandb_verify.check_wandb_version(api)
    check_run_success = wandb_verify.check_run(api)
    check_artifacts_success = wandb_verify.check_artifacts()
    if not (
        check_artifacts_success
        and check_run_success
        and large_post_success
        and url_success
    ):
        sys.exit(1)
