from functools import wraps
import logging
import os
import sys
import traceback

import click
from click.exceptions import ClickException
import six
import wandb
from wandb import Error
from wandb import util
from wandb import wandb_agent
from wandb import wandb_controller
from wandb.apis import InternalApi
from wandb.sync import SyncManager
import yaml


logger = logging.getLogger("wandb")

CONTEXT = dict(default_map={})


def cli_unsupported(argument):
    wandb.termerror("Unsupported argument `{}`".format(argument))
    sys.exit(1)


class ClickWandbException(ClickException):
    def format_message(self):
        # log_file = util.get_log_file_path()
        log_file = ""
        orig_type = '{}.{}'.format(self.orig_type.__module__,
                                   self.orig_type.__name__)
        if issubclass(self.orig_type, Error):
            return click.style(str(self.message), fg="red")
        else:
            return ('An Exception was raised, see %s for full traceback.\n'
                    '%s: %s' % (log_file, orig_type, self.message))


def display_error(func):
    """Function decorator for catching common errors and re-raising as wandb.Error"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except wandb.Error as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            lines = traceback.format_exception(
                exc_type, exc_value, exc_traceback)
            logger.error(''.join(lines))
            click_exc = ClickWandbException(e)
            click_exc.orig_type = exc_type
            six.reraise(ClickWandbException, click_exc, sys.exc_info()[2])
    return wrapper


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


@cli.command(context_settings=CONTEXT, help="Login to Weights & Biases")
@click.option("--relogin", default=None, is_flag=True, help="Force relogin if already logged in.")
@display_error
def login(relogin):
    wandb.login(relogin=relogin)


@cli.command(context_settings=CONTEXT, help="Run a SUPER agent", hidden=True)
@click.option("--project", "-p", default=None, help="The project use.")
@click.option("--entity", "-e", default=None, help="The entity to use.")
@click.argument('agent_spec', nargs=-1)
@display_error
def superagent(project=None, entity=None, agent_spec=None):
    wandb.superagent.run_agent(agent_spec)


@cli.command(context_settings=CONTEXT,
             help="Upload an offline training directory to W&B", hidden=True)
@click.pass_context
@click.argument("path", nargs=-1, type=click.Path(exists=True))
@click.option("--id", help="The run you want to upload to.")
@click.option("--project", "-p", help="The project you want to upload to.")
@click.option("--entity", "-e", help="The entity to scope to.")
@click.option("--ignore",
              help="A comma seperated list of globs to ignore syncing with wandb.")
@click.option('--all', is_flag=True, default=False, help="Sync all runs")
@display_error
def sync(ctx, path, id, project, entity, ignore, all):
    all_args = locals()
    unsupported = ("id", "project", "entity", "ignore")
    for item in unsupported:
        if all_args.get(item):
            cli_unsupported(item)
    sm = SyncManager()
    if not path:
        # Show listing of possible paths to sync
        # (if interactive, allow user to pick run to sync)
        sync_items = sm.list()
        if not sync_items:
            wandb.termerror("Nothing to sync")
            return
        if not all:
            wandb.termlog("NOTE: use sync --all to sync all unsynced runs")
            wandb.termlog("Number of runs to be synced: {}".format(len(sync_items)))
            some_runs = 5
            if some_runs < len(sync_items):
                wandb.termlog("Showing {} runs".format(some_runs))
            for item in sync_items[:some_runs]:
                wandb.termlog("  {}".format(item))
            return
        path = sync_items
    if id and len(path) > 1:
        wandb.termerror("id can only be set for a single run")
        sys.exit(1)
    for p in path:
        sm.add(p)
    sm.start()
    while not sm.is_done():
        _ = sm.poll()
        # print(status)


@cli.command(context_settings=CONTEXT, help="Create a sweep")  # noqa: C901
@click.pass_context
@click.option("--project", "-p", default=None, help="The project of the sweep.")
@click.option("--entity", "-e", default=None, help="The entity scope for the project.")
@click.option('--controller', is_flag=True, default=False, help="Run local controller")
@click.option('--verbose', is_flag=True, default=False, help="Display verbose output")
@click.option('--name', default=False, help="Set sweep name")
@click.option('--program', default=False, help="Set sweep program")
@click.option('--settings', default=False, help="Set sweep settings", hidden=True)
@click.option('--update', default=None, help="Update pending sweep")
@click.argument('config_yaml')
@display_error
def sweep(ctx, project, entity, controller, verbose, name, program, settings, update, config_yaml):
    def _parse_settings(settings):
        """settings could be json or comma seperated assignments."""
        ret = {}
        # TODO(jhr): merge with magic_impl:_parse_magic
        if settings.find('=') > 0:
            for item in settings.split(","):
                kv = item.split("=")
                if len(kv) != 2:
                    wandb.termwarn("Unable to parse sweep settings key value pair", repeat=False)
                ret.update(dict([kv]))
            return ret
        wandb.termwarn("Unable to parse settings parameter", repeat=False)
        return ret

    api = InternalApi()
    if api.api_key is None:
        wandb.termlog("Login to W&B to use the sweep feature")
        ctx.invoke(login, no_offline=True)

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
        found = api.sweep(sweep_id, '{}', entity=entity, project=project)
        if not found:
            wandb.termerror('Could not find sweep {}/{}/{}'.format(entity, project, sweep_id))
            return
        sweep_obj_id = found['id']

    wandb.termlog('{} sweep from: {}'.format(
        'Updating' if sweep_obj_id else 'Creating', config_yaml))
    try:
        yaml_file = open(config_yaml)
    except OSError:
        wandb.termerror('Couldn\'t open sweep file: %s' % config_yaml)
        return
    try:
        config = util.load_yaml(yaml_file)
    except yaml.YAMLError as err:
        wandb.termerror('Error in configuration file: %s' % err)
        return
    if config is None:
        wandb.termerror('Configuration file is empty')
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

    is_local = config.get('controller', {}).get('type') == 'local'
    if is_local:
        tuner = wandb_controller.controller()
        err = tuner._validate(config)
        if err:
            wandb.termerror('Error in sweep file: %s' % err)
            return

    env = os.environ
    entity = entity or env.get("WANDB_ENTITY") or config.get('entity')
    project = project or env.get("WANDB_PROJECT") or config.get('project') or util.auto_project_name(
        config.get("program"), api)
    sweep_id = api.upsert_sweep(config, project=project, entity=entity, obj_id=sweep_obj_id)
    wandb.termlog('{} sweep with ID: {}'.format(
        'Updated' if sweep_obj_id else 'Created',
        click.style(sweep_id, fg="yellow")))
    sweep_url = wandb_controller._get_sweep_url(api, sweep_id)
    if sweep_url:
        wandb.termlog("View sweep at: {}".format(
            click.style(sweep_url, underline=True, fg='blue')))

    # reprobe entity and project if it was autodetected by upsert_sweep
    entity = entity or env.get("WANDB_ENTITY")
    project = project or env.get("WANDB_PROJECT")

    if entity and project:
        sweep_path = "{}/{}/{}".format(entity, project, sweep_id)
    elif project:
        sweep_path = "{}/{}".format(project, sweep_id)
    else:
        sweep_path = sweep_id

    if sweep_path.find(' ') >= 0:
        sweep_path = '"{}"'.format(sweep_path)

    wandb.termlog("Run sweep agent with: {}".format(
        click.style("wandb agent %s" % sweep_path, fg="yellow")))
    if controller:
        wandb.termlog('Starting wandb controller...')
        tuner = wandb_controller.controller(sweep_id)
        tuner.run(verbose=verbose)


@cli.command(context_settings=CONTEXT, help="Run the W&B agent")
@click.pass_context
@click.option("--project", "-p", default=None, help="The project of the sweep.")
@click.option("--entity", "-e", default=None, help="The entity scope for the project.")
@click.option("--count", default=None, type=int, help="The max number of runs for this agent.")
@click.argument('sweep_id')
@display_error
def agent(ctx, project, entity, count, sweep_id):
    api = InternalApi()
    if api.api_key is None:
        wandb.termlog("Login to W&B to use the sweep agent feature")
        ctx.invoke(login, no_offline=True)

    wandb.termlog('Starting wandb agent 🕵️')
    wandb_agent.run_agent(sweep_id, entity=entity, project=project, count=count)

    # you can send local commands like so:
    # agent_api.command({'type': 'run', 'program': 'train.py',
    #                'args': ['--max_epochs=10']})


@cli.command(context_settings=CONTEXT, help="Run the W&B local sweep controller")
@click.option('--verbose', is_flag=True, default=False, help="Display verbose output")
@click.argument('sweep_id')
@display_error
def controller(verbose, sweep_id):
    click.echo('Starting wandb controller...')
    tuner = wandb_controller.controller(sweep_id)
    tuner.run(verbose=verbose)
