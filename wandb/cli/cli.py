#!/usr/bin/env python
# -*- coding: utf-8 -*-

import copy
import datetime
from functools import wraps
import getpass
import json
import logging
import os
import shutil
import subprocess
import sys
import textwrap
import time
import traceback

import click
from click.exceptions import ClickException

# pycreds has a find_executable that works in windows
from dockerpycreds.utils import find_executable
import six
from six.moves import configparser
import wandb
from wandb import Config
from wandb import env, util
from wandb import Error
from wandb import wandb_agent
from wandb import wandb_controller
from wandb import wandb_sdk

from wandb.apis import InternalApi, PublicApi
from wandb.compat import tempfile
from wandb.integration.magic import magic_install

# from wandb.old.core import wandb_dir
from wandb.sync import get_run_from_path, get_runs, SyncManager, TMPDIR
import yaml

PY3 = sys.version_info.major == 3 and sys.version_info.minor >= 6
if PY3:
    import wandb.sdk.verify.verify as wandb_verify
else:
    import wandb.sdk_py27.verify.verify as wandb_verify


# TODO: turn this on in a cleaner way
# right now we will litter the filesystem with wandb dirs
#
# _wandb_dir = wandb_dir(env.get_dir())
# wandb.wandb_sdk.lib.filesystem._safe_makedirs(_wandb_dir)
# logging.basicConfig(
#     filename=os.path.join(_wandb_dir, "debug-cli.log"),
#     level=logging.DEBUG,
# )
# logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)
logger = logging.getLogger("wandb")

CONTEXT = dict(default_map={})


def cli_unsupported(argument):
    wandb.termerror("Unsupported argument `{}`".format(argument))
    sys.exit(1)


class ClickWandbException(ClickException):
    def format_message(self):
        # log_file = util.get_log_file_path()
        log_file = ""
        orig_type = "{}.{}".format(self.orig_type.__module__, self.orig_type.__name__)
        if issubclass(self.orig_type, Error):
            return click.style(str(self.message), fg="red")
        else:
            return "An Exception was raised, see %s for full traceback.\n" "%s: %s" % (
                log_file,
                orig_type,
                self.message,
            )


def display_error(func):
    """Function decorator for catching common errors and re-raising as wandb.Error"""

    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except wandb.Error as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
            logger.error("".join(lines))
            click_exc = ClickWandbException(e)
            click_exc.orig_type = exc_type
            six.reraise(ClickWandbException, click_exc, sys.exc_info()[2])

    return wrapper


_api = None  # caching api instance allows patching from unit tests


def _get_cling_api(reset=None):
    """Get a reference to the internal api with cling settings."""
    global _api
    if reset:
        _api = None
        wandb_sdk.wandb_setup._setup(_reset=True)
    if _api is None:
        # TODO(jhr): make a settings object that is better for non runs.
        wandb.setup(settings=wandb.Settings(_cli_only_mode=True))
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
    # wandb.try_to_set_up_global_logging()
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
        message = "No projects found for %s" % entity
    else:
        message = 'Latest projects for "%s"' % entity
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
@display_error
def login(key, host, cloud, relogin, anonymously, no_offline=False):
    # TODO: handle no_offline
    anon_mode = "must" if anonymously else "never"

    if host and not host.startswith("http"):
        raise ClickException("host must start with http(s)://")

    wandb_sdk.wandb_login._handle_host_wandb_setting(host, cloud)
    key = key[0] if len(key) > 0 else None
    if key:
        relogin = True

    try:
        wandb.setup(
            settings=wandb.Settings(
                _cli_only_mode=True,
                _disable_viewer=relogin,
                anonymous=anon_mode,
                base_url=host,
            )
        )
    except TypeError as e:
        wandb.termerror(str(e))
        sys.exit(1)

    wandb.login(relogin=relogin, key=key, anonymous=anon_mode, host=host, force=True)


@cli.command(
    context_settings=CONTEXT, help="Run a grpc server", name="grpc-server", hidden=True
)
@click.option("--port", default=None, help="The host port to bind grpc service.")
@display_error
def grpc_server(project=None, entity=None, port=None):
    _ = util.get_module(
        "grpc",
        required="grpc-server requires the grpcio library, run pip install wandb[grpc]",
    )
    from wandb.server.grpc_server import main as grpc_server

    grpc_server(port=port)


@cli.command(context_settings=CONTEXT, help="Run a SUPER agent", hidden=True)
@click.option("--project", "-p", default=None, help="The project to use.")
@click.option("--entity", "-e", default=None, help="The entity to use.")
@click.argument("agent_spec", nargs=-1)
@display_error
def superagent(project=None, entity=None, agent_spec=None):
    wandb.superagent.run_agent(agent_spec)


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
    from wandb.old.core import _set_stage_dir, __stage_dir__, wandb_dir

    if __stage_dir__ is None:
        _set_stage_dir("wandb")

    # non interactive init
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
                "We're sorry, there was a problem logging you in. Please send us a note at support@wandb.com and tell us how this happened.",
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
        wandb.termlog("Which team should we use?",)
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
        raise ClickException("Could not find team: %s" % entity)

    api.set_setting("entity", entity, persist=True)
    api.set_setting("project", project, persist=True)
    api.set_setting("base_url", api.settings().get("base_url"), persist=True)

    util.mkdir_exists_ok(wandb_dir())
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
            code2=click.style('wandb.init(project="%s")' % project, bold=True),
            run=click.style("python <train.py>", bold=True),
        )
    )


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
    "--sync-tensorboard/--no-sync-tensorboard",
    is_flag=True,
    default=None,
    help="Stream tfevent files to wandb.",
)
@click.option("--include-globs", help="Comma seperated list of globs to include.")
@click.option("--exclude-globs", help="Comma seperated list of globs to exclude.")
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
@display_error
def sync(
    ctx,
    path=None,
    view=None,
    verbose=None,
    run_id=None,
    project=None,
    entity=None,
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
):
    # TODO: rather unfortunate, needed to avoid creating a `wandb` directory
    os.environ["WANDB_DIR"] = TMPDIR.name
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
            wandb.termlog("Number of runs to be synced: {}".format(len(sync_items)))
            if show and show < len(sync_items):
                wandb.termlog("Showing {} runs to be synced:".format(show))
            for item in sync_items[: (show or len(sync_items))]:
                wandb.termlog("  {}".format(item))
        else:
            wandb.termlog("No runs to be synced.")
        if synced:
            clean_cmd = click.style("wandb sync --clean", fg="yellow")
            wandb.termlog(
                "NOTE: use {} to delete {} synced runs from local directory.".format(
                    clean_cmd, len(synced)
                )
            )
        if unsynced:
            sync_cmd = click.style("wandb sync --sync-all", fg="yellow")
            wandb.termlog(
                "NOTE: use {} to sync {} unsynced runs from local directory.".format(
                    sync_cmd, len(unsynced)
                )
            )

    def _sync_path(path, sync_tensorboard):
        if run_id and len(path) > 1:
            wandb.termerror("id can only be set for a single run.")
            sys.exit(1)
        sm = SyncManager(
            project=project,
            entity=entity,
            run_id=run_id,
            mark_synced=mark_synced,
            app_url=api.app_url,
            view=view,
            verbose=verbose,
            sync_tensorboard=sync_tensorboard,
        )
        for p in path:
            sm.add(p)
        sm.start()
        while not sm.is_done():
            _ = sm.poll()
            # print(status)

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
                        "Are you sure you want to remove %i runs?" % len(runs),
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
        old_runs.sort(key=lambda run: run.datetime)
        if old_runs:
            click.echo(
                "Found {} runs, {} are older than {} hours".format(
                    len(runs), len(old_runs), clean_old_hours
                )
            )
            for run in old_runs:
                click.echo(run.path)
            if not clean_force:
                click.confirm(
                    click.style(
                        "Are you sure you want to remove %i runs?" % len(old_runs),
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
                    "No runs older than %i hours found" % clean_old_hours, fg="red"
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


@cli.command(context_settings=CONTEXT, help="Create a sweep")  # noqa: C901
@click.pass_context
@click.option("--project", "-p", default=None, help="The project of the sweep.")
@click.option("--entity", "-e", default=None, help="The entity scope for the project.")
@click.option("--controller", is_flag=True, default=False, help="Run local controller")
@click.option("--verbose", is_flag=True, default=False, help="Display verbose output")
@click.option("--name", default=False, help="Set sweep name")
@click.option("--program", default=False, help="Set sweep program")
@click.option("--settings", default=False, help="Set sweep settings", hidden=True)
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
@click.argument("config_yaml_or_sweep_id")
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
    config_yaml_or_sweep_id,
):  # noqa: C901
    state_args = "stop", "cancel", "pause", "resume"
    lcls = locals()
    is_state_change_command = sum((lcls[k] for k in state_args))
    if is_state_change_command > 1:
        raise Exception("Only one state flag (stop/cancel/pause/resume) is allowed.")
    elif is_state_change_command == 1:
        sweep_id = config_yaml_or_sweep_id
        api = _get_cling_api()
        if api.api_key is None:
            wandb.termlog("Login to W&B to use the sweep feature")
            ctx.invoke(login, no_offline=True)
            api = _get_cling_api(reset=True)
        parts = dict(entity=entity, project=project, name=sweep_id)
        err = util.parse_sweep_id(parts)
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
        wandb.termlog(
            "%s sweep %s." % (ings[state], "%s/%s/%s" % (entity, project, sweep_id))
        )
        getattr(api, "%s_sweep" % state)(sweep_id, entity=entity, project=project)
        wandb.termlog("Done.")
        return
    else:
        config_yaml = config_yaml_or_sweep_id

    def _parse_settings(settings):
        """settings could be json or comma seperated assignments."""
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
    if api.api_key is None:
        wandb.termlog("Login to W&B to use the sweep feature")
        ctx.invoke(login, no_offline=True)
        api = _get_cling_api(reset=True)

    sweep_obj_id = None
    if update:
        parts = dict(entity=entity, project=project, name=update)
        err = util.parse_sweep_id(parts)
        if err:
            wandb.termerror(err)
            return
        entity = parts.get("entity") or entity
        project = parts.get("project") or project
        sweep_id = parts.get("name") or update
        found = api.sweep(sweep_id, "{}", entity=entity, project=project)
        if not found:
            wandb.termerror(
                "Could not find sweep {}/{}/{}".format(entity, project, sweep_id)
            )
            return
        sweep_obj_id = found["id"]

    wandb.termlog(
        "{} sweep from: {}".format(
            "Updating" if sweep_obj_id else "Creating", config_yaml
        )
    )
    try:
        yaml_file = open(config_yaml)
    except OSError:
        wandb.termerror("Couldn't open sweep file: %s" % config_yaml)
        return
    try:
        config = util.load_yaml(yaml_file)
    except yaml.YAMLError as err:
        wandb.termerror("Error in configuration file: %s" % err)
        return
    if config is None:
        wandb.termerror("Configuration file is empty")
        return

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
        tuner = wandb_controller.controller()
        err = tuner._validate(config)
        if err:
            wandb.termerror("Error in sweep file: %s" % err)
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
        config, project=project, entity=entity, obj_id=sweep_obj_id
    )
    util.handle_sweep_config_violations(warnings)

    wandb.termlog(
        "{} sweep with ID: {}".format(
            "Updated" if sweep_obj_id else "Created", click.style(sweep_id, fg="yellow")
        )
    )

    sweep_url = wandb_controller._get_sweep_url(api, sweep_id)
    if sweep_url:
        wandb.termlog(
            "View sweep at: {}".format(
                click.style(sweep_url, underline=True, fg="blue")
            )
        )

    # reprobe entity and project if it was autodetected by upsert_sweep
    entity = entity or env.get("WANDB_ENTITY")
    project = project or env.get("WANDB_PROJECT")

    if entity and project:
        sweep_path = "{}/{}/{}".format(entity, project, sweep_id)
    elif project:
        sweep_path = "{}/{}".format(project, sweep_id)
    else:
        sweep_path = sweep_id

    if sweep_path.find(" ") >= 0:
        sweep_path = '"{}"'.format(sweep_path)

    wandb.termlog(
        "Run sweep agent with: {}".format(
            click.style("wandb agent %s" % sweep_path, fg="yellow")
        )
    )
    if controller:
        wandb.termlog("Starting wandb controller...")
        tuner = wandb_controller.controller(sweep_id)
        tuner.run(verbose=verbose)


@cli.command(context_settings=CONTEXT, help="Run the W&B agent")
@click.pass_context
@click.option("--project", "-p", default=None, help="The project of the sweep.")
@click.option("--entity", "-e", default=None, help="The entity scope for the project.")
@click.option(
    "--count", default=None, type=int, help="The max number of runs for this agent."
)
@click.argument("sweep_id")
@display_error
def agent(ctx, project, entity, count, sweep_id):
    api = _get_cling_api()
    if api.api_key is None:
        wandb.termlog("Login to W&B to use the sweep agent feature")
        ctx.invoke(login, no_offline=True)
        api = _get_cling_api(reset=True)

    wandb.termlog("Starting wandb agent 🕵️")
    wandb_agent.agent(sweep_id, entity=entity, project=project, count=count)

    # you can send local commands like so:
    # agent_api.command({'type': 'run', 'program': 'train.py',
    #                'args': ['--max_epochs=10']})


@cli.command(context_settings=CONTEXT, help="Run the W&B local sweep controller")
@click.option("--verbose", is_flag=True, default=False, help="Display verbose output")
@click.argument("sweep_id")
@display_error
def controller(verbose, sweep_id):
    click.echo("Starting wandb controller...")
    tuner = wandb_controller.controller(sweep_id)
    tuner.run(verbose=verbose)


RUN_CONTEXT = copy.copy(CONTEXT)
RUN_CONTEXT["allow_extra_args"] = True
RUN_CONTEXT["ignore_unknown_options"] = True


@cli.command(context_settings=RUN_CONTEXT, name="docker-run")
@click.pass_context
@click.argument("docker_run_args", nargs=-1)
def docker_run(ctx, docker_run_args):
    """Simple wrapper for `docker run` which adds WANDB_API_KEY and WANDB_DOCKER
    environment variables to any docker run command.

    This will also set the runtime to nvidia if the nvidia-docker executable is present on the system
    and --runtime wasn't set.

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
        args = ["-e", "WANDB_DOCKER=%s" % resolved_image] + args
    else:
        wandb.termlog(
            "Couldn't detect image argument, running command without the WANDB_DOCKER env variable"
        )
    if api.api_key:
        args = ["-e", "WANDB_API_KEY=%s" % api.api_key] + args
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
    """W&B docker lets you run your code in a docker image ensuring wandb is configured. It adds the WANDB_DOCKER and WANDB_API_KEY
    environment variables to your container and mounts the current directory in /app by default.  You can pass additional
    args which will be added to `docker run` before the image name is declared, we'll choose a default image for you if
    one isn't passed:

    wandb docker -v /mnt/dataset:/app/data
    wandb docker gcr.io/kubeflow-images-public/tensorflow-1.12.0-notebook-cpu:v0.4.0 --jupyter
    wandb docker wandb/deepo:keras-gpu --no-tty --cmd "python train.py --epochs=5"

    By default we override the entrypoint to check for the existance of wandb and install it if not present.  If you pass the --jupyter
    flag we will ensure jupyter is installed and start jupyter lab on port 8888.  If we detect nvidia-docker on your system we will use
    the nvidia runtime.  If you just want wandb to set environment variable to an existing docker run command, see the wandb docker-run
    command.
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
            "Couldn't find image locally or in a registry, try running `docker pull %s`"
            % image
        )
    if digest:
        sys.stdout.write(resolved_image)
        exit(0)

    existing = wandb.docker.shell(["ps", "-f", "ancestor=%s" % resolved_image, "-q"])
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
        "WANDB_DOCKER=%s" % resolved_image,
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
        command.extend(["-e", "WANDB_API_KEY=%s" % api.api_key])
    else:
        wandb.termlog(
            "Couldn't find WANDB_API_KEY, run `wandb login` to enable streaming metrics"
        )
    if jupyter:
        command.extend(["-e", "WANDB_ENSURE_JUPYTER=1", "-p", port + ":8888"])
        no_tty = True
        cmd = (
            "jupyter lab --no-browser --ip=0.0.0.0 --allow-root --NotebookApp.token= --notebook-dir %s"
            % dir
        )
    command.extend(args)
    if no_tty:
        command.extend([image, shell, "-c", cmd])
    else:
        if cmd:
            command.extend(["-e", "WANDB_COMMAND=%s" % cmd])
        command.extend(["-it", image, shell])
        wandb.termlog("Launching docker container \U0001F6A2")
    subprocess.call(command)


@cli.command(
    context_settings=RUN_CONTEXT, help="Launch local W&B container (Experimental)"
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
    "--edge", is_flag=True, default=False, help="Run the bleading edge", hidden=True
)
@display_error
def local(ctx, port, env, daemon, upgrade, edge):
    api = InternalApi()
    if not find_executable("docker"):
        raise ClickException("Docker not installed, install it from https://docker.com")
    if wandb.docker.image_id("wandb/local") != wandb.docker.image_id_from_registry(
        "wandb/local"
    ):
        if upgrade:
            subprocess.call(["docker", "pull", "wandb/local"])
        else:
            wandb.termlog(
                "A new version of W&B local is available, upgrade by calling `wandb local --upgrade`"
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
    env_vars = ["-e", "LOCAL_USERNAME=%s" % username]
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
    host = "http://localhost:%s" % port
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
                "Failed to launch the W&B local container, see the above error."
            )
            exit(1)
        else:
            wandb.termlog("W&B local started at http://localhost:%s \U0001F680" % port)
            wandb.termlog(
                "You can stop the server by running `docker stop wandb-local`"
            )
            if not api.api_key:
                # Let the server start before potentially launching a browser
                time.sleep(2)
                ctx.invoke(login, host=host)


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
@display_error
def put(path, name, description, type, alias):
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
    artifact_path = "{entity}/{project}/{name}:{alias}".format(
        entity=entity, project=project, name=artifact_name, alias=alias[0]
    )
    if os.path.isdir(path):
        wandb.termlog(
            'Uploading directory {path} to: "{artifact_path}" ({type})'.format(
                path=path, type=type, artifact_path=artifact_path
            )
        )
        artifact.add_dir(path)
    elif os.path.isfile(path):
        wandb.termlog(
            'Uploading file {path} to: "{artifact_path}" ({type})'.format(
                path=path, type=type, artifact_path=artifact_path
            )
        )
        artifact.add_file(path)
    elif "://" in path:
        wandb.termlog(
            'Logging reference artifact from {path} to: "{artifact_path}" ({type})'.format(
                path=path, type=type, artifact_path=artifact_path
            )
        )
        artifact.add_reference(path)
    else:
        raise ClickException("Path argument must be a file or directory")

    run = wandb.init(
        entity=entity, project=project, config={"path": path}, job_type="cli_put"
    )
    # We create the artifact manually to get the current version
    res, _ = api.create_artifact(
        type,
        artifact_name,
        artifact.digest,
        entity_name=entity,
        project_name=project,
        run_name=run.id,
        description=description,
        aliases=[{"artifactCollectionName": artifact_name, "alias": a} for a in alias],
    )
    artifact_path = artifact_path.split(":")[0] + ":" + res.get("version", "latest")
    # Re-create the artifact and actually upload any files needed
    run.log_artifact(artifact, aliases=alias)
    wandb.termlog(
        "Artifact uploaded, use this artifact in a run by adding:\n", prefix=False
    )

    wandb.termlog(
        '    artifact = run.use_artifact("{path}")\n'.format(path=artifact_path,),
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
        full_path = "{entity}/{project}/{artifact}:{version}".format(
            entity=entity, project=project, artifact=artifact_name, version=version
        )
        wandb.termlog(
            "Downloading {type} artifact {full_path}".format(
                type=type or "dataset", full_path=full_path
            )
        )
        artifact = public_api.artifact(full_path, type=type)
        path = artifact.download(root=root)
        wandb.termlog("Artifact downloaded to %s" % path)
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
@display_error
def cleanup(target_size):
    target_size = util.from_human_size(target_size)
    cache = wandb_sdk.wandb_artifacts.get_artifacts_cache()
    reclaimed_bytes = cache.cleanup(target_size)
    print("Reclaimed {} of space".format(util.to_human_size(reclaimed_bytes)))


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
    click.echo(
        "Downloading: {project}/{run}".format(
            project=click.style(project, bold=True), run=run
        )
    )

    for name in urls:
        if api.file_current(name, urls[name]["md5"]):
            click.echo("File %s is up to date" % name)
        else:
            length, response = api.download_file(urls[name]["url"])
            # TODO: I had to add this because some versions in CI broke click.progressbar
            sys.stdout.write("File %s\r" % name)
            dirname = os.path.dirname(name)
            if dirname != "":
                wandb.util.mkdir_exists_ok(dirname)
            with click.progressbar(
                length=length,
                label="File %s" % name,
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
@click.option("--no-git", is_flag=True, default=False, help="Skupp")
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
    restore_message = (
        """`wandb restore` needs to be run from the same git repository as the original run.
Run `git clone %s` and restore from there or pass the --no-git flag."""
        % repo
    )
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
        wandb.termlog("Fetching origin and finding commit: {}".format(commit))
        subprocess.check_call(["git", "fetch", "--all"])
        try:
            api.git.repo.commit(commit)
        except ValueError:
            wandb.termlog("Couldn't find original commit: {}".format(commit))
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
                wandb.termlog("Falling back to upstream commit: {}".format(commit))
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

        branch_name = "wandb/%s" % run
        if branch and branch_name not in api.git.repo.branches:
            api.git.repo.git.checkout(commit, b=branch_name)
            wandb.termlog("Created branch %s" % click.style(branch_name, bold=True))
        elif branch:
            wandb.termlog(
                "Using existing branch, run `git branch -D %s` from master for a clean checkout"
                % branch_name
            )
            api.git.repo.git.checkout(branch_name)
        else:
            wandb.termlog("Checking out %s in detached mode" % commit)
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

    util.mkdir_exists_ok(wandb_dir())
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

    wandb.termlog("Restored config variables to %s" % config_path)
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
    except IOError:
        click.echo(click.style("Could not launch program: %s" % program, fg="red"))
        sys.exit(1)
    globs = {
        "__file__": program,
        "__name__": "__main__",
        "__package__": None,
        "wandb_magic_install": magic_install,
    }
    prep = (
        """
import __main__
__main__.__file__ = "%s"
wandb_magic_install()
"""
        % program
    )
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
        "W&B online, running your script from this directory will now sync to the cloud."
    )


@cli.command("offline", help="Disable W&B sync")
@display_error
def offline():
    api = InternalApi()
    try:
        api.set_setting("disabled", "true", persist=True)
        api.set_setting("mode", "offline", persist=True)
        click.echo(
            "W&B offline, running your script from this directory will only write metadata locally."
        )
    except configparser.Error:
        click.echo(
            "Unable to write config, copy and paste the following in your terminal to turn off W&B:\nexport WANDB_MODE=dryrun"
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
def disabled():
    api = InternalApi()
    try:
        api.set_setting("mode", "disabled", persist=True)
        click.echo("W&B disabled.")
    except configparser.Error:
        click.echo(
            "Unable to write config, copy and paste the following in your terminal to turn off W&B:\nexport WANDB_MODE=disabled"
        )


@cli.command("enabled", help="Enable W&B.")
def enabled():
    api = InternalApi()
    try:
        api.set_setting("mode", "online", persist=True)
        click.echo("W&B enabled.")
    except configparser.Error:
        click.echo(
            "Unable to write config, copy and paste the following in your terminal to turn off W&B:\nexport WANDB_MODE=online"
        )


@cli.command("gc", hidden=True, context_settings={"ignore_unknown_options": True})
@click.argument("args", nargs=-1)
def gc(args):
    click.echo(
        "`wandb gc` command has been removed. Use `wandb sync --clean` to clean up synced runs."
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
        print("Default host selected: {}".format(host))
    # if the given host does not match the default host, re run init
    elif host != api.settings("base_url"):
        reinit = True

    tmp_dir = tempfile.TemporaryDirectory()
    os.chdir(tmp_dir.name)
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
