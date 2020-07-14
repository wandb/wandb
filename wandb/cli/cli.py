from functools import wraps
import logging
import os
import sys
import traceback

import click
from click.exceptions import ClickException
import six
import wandb
from wandb import env, util
from wandb import Error
from wandb import wandb_agent
from wandb import wandb_controller
from wandb.apis import InternalApi, PublicApi
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


@cli.group(help="Commands for interacting with artifacts")
def artifact():
    pass


@artifact.command(context_settings=CONTEXT, help="Upload an artifact to wandb")
@click.argument("path")
@click.option("--name", "-n", help="The name of the artifact to push: project/artifact_name")
@click.option("--description", "-d", help="A description of this artifact")
@click.option("--type", "-t", default="dataset", help="The type of the artifact")
@click.option("--alias", "-a", default=["latest"], multiple=True, help="An alias to apply to this artifact")
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
    artifact_path = "{entity}/{project}/{name}:{alias}".format(entity=entity,
                                                               project=project, name=artifact_name, alias=alias[0])
    if os.path.isdir(path):
        wandb.termlog("Uploading directory {path} to: \"{artifact_path}\" ({type})".format(
            path=path, type=type, artifact_path=artifact_path))
        artifact.add_dir(path)
    elif os.path.isfile(path):
        wandb.termlog("Uploading file {path} to: \"{artifact_path}\" ({type})".format(
            path=path, type=type, artifact_path=artifact_path))
        artifact.add_file(path)
    elif "://" in path:
        wandb.termlog("Logging reference artifact from {path} to: \"{artifact_path}\" ({type})".format(
            path=path, type=type, artifact_path=artifact_path))
        artifact.add_reference(path)
    else:
        raise ClickException("Path argument must be a file or directory")

    run = wandb.init(entity=entity, project=project, config={"path": path}, job_type="cli_put")
    # We create the artifact manually to get the current version
    res = api.create_artifact(type, artifact_name, artifact.digest,
                              entity_name=entity, project_name=project, run_name=run.id, description=description,
                              aliases=[{"artifactCollectionName": artifact_name, "alias": a} for a in alias])
    artifact_path = artifact_path.split(":")[0] + ":" + res.get("version", "latest")
    # Re-create the artifact and actually upload any files needed
    run.log_artifact(artifact, aliases=alias)
    wandb.termlog("Artifact uploaded, use this artifact in a run by adding:\n", prefix=False)

    wandb.termlog("    artifact = run.use_artifact(\"{path}\")\n".format(
        path=artifact_path,
    ), prefix=False)


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
            entity=entity, project=project,
            artifact=artifact_name, version=version)
        wandb.termlog("Downloading {type} artifact {full_path}".format(
            type=type or "dataset", full_path=full_path))
        artifact = public_api.artifact(full_path, type=type)
        path = artifact.download(root=root)
        wandb.termlog("Artifact downloaded to %s" % path)
    except ValueError:
        raise ClickException("Unable to download artifact")


@artifact.command(context_settings=CONTEXT, help="List all artifacts in a wandb project")
@click.argument("path")
@click.option("--type", "-t", help="The type of artifacts to list")
@display_error
def ls(path, type):
    public_api = PublicApi()
    if type is not None:
        types = [public_api.artifact_type(type, path)]
    else:
        types = public_api.artifact_types(path)

    def human_size(bytes, units=None):
        units = units or ['', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB']
        return str(bytes) + units[0] if bytes < 1024 else human_size(bytes >> 10, units[1:])

    for kind in types:
        for collection in kind.collections():
            versions = public_api.artifact_versions(kind.type, "/".join([kind.entity, kind.project, collection.name]),
                                                    per_page=1)
            latest = next(versions)
            print("{:<15s}{:<15s}{:>15s} {:<20s}".format(kind.type, latest.updated_at, human_size(latest.size),
                                                         latest.name))


@cli.command(context_settings=CONTEXT, help="Pull files from Weights & Biases")
@click.argument("run", envvar=env.RUN_ID)
@click.option("--project", "-p", envvar=env.PROJECT, help="The project you want to download.")
@click.option("--entity", "-e", default="models", envvar=env.ENTITY, help="The entity to scope the listing to.")
@display_error
def pull(run, project, entity):
    api = InternalApi()
    project, run = api.parse_slug(run, project=project)
    urls = api.download_urls(project, run=run, entity=entity)
    if len(urls) == 0:
        raise ClickException("Run has no files")
    click.echo("Downloading: {project}/{run}".format(
        project=click.style(project, bold=True), run=run
    ))

    for name in urls:
        if api.file_current(name, urls[name]['md5']):
            click.echo("File %s is up to date" % name)
        else:
            length, response = api.download_file(urls[name]['url'])
            # TODO: I had to add this because some versions in CI broke click.progressbar
            sys.stdout.write("File %s\r" % name)
            dirname = os.path.dirname(name)
            if dirname != '':
                wandb.util.mkdir_exists_ok(dirname)
            with click.progressbar(length=length, label='File %s' % name,
                                   fill_char=click.style('&', fg='green')) as bar:
                with open(name, "wb") as f:
                    for data in response.iter_content(chunk_size=4096):
                        f.write(data)
                        bar.update(len(data))
