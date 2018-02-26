# -*- coding: utf-8 -*-
from __future__ import print_function

import click
import copy
from functools import wraps
import glob
import io
import json
import logging
import netrc
import os
import random
import re
import requests
import shlex
import signal
import socket
import stat
import subprocess
import sys
import textwrap
import time
import traceback
import yaml
import threading

from click.utils import LazyFile
from click.exceptions import BadParameter, ClickException
import whaaaaat

import wandb
from wandb.api import Api
from wandb.config import Config
from wandb import agent as wandb_agent
from wandb import wandb_run
from wandb import wandb_dir
from wandb import util
from wandb import run_manager
from wandb import Error

DOCS_URL = 'http://docs.wandb.com/'
logger = logging.getLogger(__name__)


class ClickWandbException(ClickException):
    def format_message(self):
        log_file = util.get_log_file_path()
        orig_type = '%s.%s' % (self.orig_type.__module__,
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
            raise click_exc
    return wrapper


IS_INIT = False


def _require_init():
    if not IS_INIT and wandb.__stage_dir__ is None:
        print('Directory not initialized. Please run "wandb init" to get started.')
        sys.exit(1)


def require_init(func):
    """Function decorator for catching common errors and re-raising as wandb.Error"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        _require_init()
        return func(*args, **kwargs)
    return wrapper


def prompt_for_project(ctx, entity):
    """Ask the user for a project, creating one if necessary."""
    result = ctx.invoke(projects, entity=entity, display=False)

    try:
        if len(result) == 0:
            project = click.prompt("Enter a name for your first project")
            #description = editor()
            project = api.upsert_project(project, entity=entity)["name"]
        else:
            project_names = [project["name"] for project in result]
            question = {
                'type': 'list',
                'name': 'project_name',
                'message': "Which project should we use?",
                'choices': project_names + ["Create New"]
            }
            project = whaaaaat.prompt([question])['project_name']

            # TODO: check with the server if the project exists
            if project == "Create New":
                project = click.prompt(
                    "Enter a name for your new project", value_proc=api.format_project)
                #description = editor()
                project = api.upsert_project(project, entity=entity)["name"]

    except wandb.api.CommError as e:
        raise ClickException(str(e))

    return project


def write_netrc(host, entity, key):
    """Add our host and key to .netrc"""
    if len(key) != 40:
        click.secho(
            'API-key must be exactly 40 characters long: %s (%s chars)' % (key, len(key)))
        return None
    try:
        print("Appending to netrc %s" % os.path.expanduser('~/.netrc'))
        normalized_host = host.split("/")[-1].split(":")[0]
        machine_line = 'machine %s' % normalized_host
        path = os.path.expanduser('~/.netrc')
        orig_lines = None
        try:
            with open(path) as f:
                orig_lines = f.read().strip().split('\n')
        except (IOError, OSError) as e:
            pass
        with open(path, 'w') as f:
            if orig_lines:
                # delete this machine from the file if it's already there.
                skip = 0
                for line in orig_lines:
                    if machine_line in line:
                        skip = 2
                    elif skip:
                        skip -= 1
                    else:
                        f.write('%s\n' % line)
            f.write(textwrap.dedent("""\
            machine {host}
              login {entity}
              password {key}
            """).format(host=normalized_host, entity=entity, key=key))
        os.chmod(os.path.expanduser('~/.netrc'),
                 stat.S_IRUSR | stat.S_IWUSR)
    except IOError as e:
        click.secho("Unable to read ~/.netrc", fg="red")
        return None


def editor(content='', marker='# Enter a description, markdown is allowed!\n'):
    message = click.edit(content + '\n\n' + marker)
    if message is not None:
        return message.split(marker, 1)[0].rstrip('\n')


api = Api()

# Some commands take project/entity etc. as arguments. We provide default
# values for those arguments from the current project configuration, as
# returned by api.settings()
CONTEXT = dict(default_map=api.settings())


class RunGroup(click.Group):
    @display_error
    def get_command(self, ctx, cmd_name):
        # TODO: check if cmd_name is a file in the current dir and not require `run`?
        rv = click.Group.get_command(self, ctx, cmd_name)
        if rv is not None:
            return rv

        return None


@click.command(cls=RunGroup)
@click.version_option(version=wandb.__version__)
@click.pass_context
def cli(ctx):
    """Weights & Biases.

    Run "wandb docs" for full documentation.
    """
    pass


@cli.command(context_settings=CONTEXT, help="List projects")
@require_init
@click.option("--entity", "-e", default="models", envvar='WANDB_ENTITY', help="The entity to scope the listing to.")
@display_error
def projects(entity, display=True):
    projects = api.list_projects(entity=entity)
    if len(projects) == 0:
        message = "No projects found for %s" % entity
    else:
        message = 'Latest projects for "%s"' % entity
    if display:
        click.echo(click.style(message, bold=True))
        for project in projects:
            click.echo("".join(
                (click.style(project['name'], fg="blue", bold=True),
                 " - ",
                 str(project['description'] or "").split("\n")[0])
            ))
    return projects


@cli.command(context_settings=CONTEXT, help="List runs in a project")
@click.pass_context
@click.option("--project", "-p", default=None, envvar='WANDB_PROJECT', help="The project you wish to list runs from.")
@click.option("--entity", "-e", default="models", envvar='WANDB_ENTITY', help="The entity to scope the listing to.")
@display_error
@require_init
def runs(ctx, project, entity):
    click.echo(click.style('Latest runs for project "%s"' %
                           project, bold=True))
    if project is None:
        project = prompt_for_project(ctx, project)
    runs = api.list_runs(project, entity=entity)
    for run in runs:
        click.echo("".join(
            (click.style(run['name'], fg="blue", bold=True),
             " - ",
             (run['description'] or "").split("\n")[0])
        ))


@cli.command(context_settings=CONTEXT, help="List local & remote file status")
@click.argument("run", envvar='WANDB_RUN')
@click.option("--settings/--no-settings", help="Show the current settings", default=True)
@click.option("--project", "-p", envvar='WANDB_PROJECT', help="The project you wish to upload to.")
@display_error
def status(run, settings, project):
    if settings:
        click.echo(click.style("Logged in?", bold=True) + " %s" %
                   bool(api.api_key))
        click.echo(click.style("Current Settings", bold=True) +
                   " (%s)" % api.settings_file)
        settings = api.settings()
        click.echo(json.dumps(
            settings,
            sort_keys=True,
            indent=2,
            separators=(',', ': ')
        ))


@cli.command(context_settings=CONTEXT, help="Restore code and config state for a run")
@click.argument("run", envvar='WANDB_RUN')
@click.option("--branch/--no-branch", default=True, help="Whether to create a branch or checkout detached")
@click.option("--project", "-p", envvar='WANDB_PROJECT', help="The project you wish to upload to.")
@click.option("--entity", "-e", default="models", envvar='WANDB_ENTITY', help="The entity to scope the listing to.")
@display_error
def restore(run, branch, project, entity):
    project, run = api.parse_slug(run, project=project)
    commit, json_config, patch_content = api.run_config(
        project, run=run, entity=entity)
    subprocess.check_call(['git', 'fetch', '--all'])

    if commit:
        try:
            api.git.repo.commit(commit)
        except ValueError:
            click.echo("Couldn't find original commit: {}".format(commit))
            commit = None
            files = api.download_urls(project, run=run, entity=entity)
            for filename in files:
                if filename.startswith('upstream_diff_') and filename.endswith('.patch'):
                    commit = filename[len('upstream_diff_'):-len('.patch')]
                    try:
                        api.git.repo.commit(commit)
                    except ValueError:
                        commit = None
                    else:
                        break

            if commit:
                click.echo(
                    "Falling back to upstream commit: {}".format(commit))
                patch_path, _ = api.download_write_file(files[filename])
            else:
                raise ClickException(
                    "Can't find commit from which to restore code")
        else:
            if patch_content:
                patch_path = os.path.join(wandb.__stage_dir__, 'diff.patch')
                with open(patch_path, "w") as f:
                    f.write(patch_content)
            else:
                patch_path = None

        branch_name = "wandb/%s" % run
        if branch and branch_name not in api.git.repo.branches:
            api.git.repo.git.checkout(commit, b=branch_name)
            click.echo("Created branch %s" %
                       click.style(branch_name, bold=True))
        elif branch:
            click.secho(
                "Using existing branch, run `git branch -D %s` from master for a clean checkout" % branch_name, fg="red")
            api.git.repo.git.checkout(branch_name)
        else:
            click.secho("Checking out %s in detached mode" % commit)
            api.git.repo.git.checkout(commit)

        if patch_path:
            # we apply the patch from the repository root so git doesn't exclude
            # things outside the current directory
            root = api.git.root
            patch_rel_path = os.path.relpath(patch_path, start=root)
            # --reject is necessary or else this fails any time a binary file
            # occurs in the diff
            # we use .call() instead of .check_call() for the same reason
            # TODO(adrian): this means there is no error checking here
            subprocess.call(['git', 'apply', '--reject',
                             patch_rel_path], cwd=root)
            click.echo("Applied patch")

    config = Config()
    config.load_json(json_config)
    config.persist()
    click.echo("Restored config variables")


@cli.command(context_settings=CONTEXT, help="Pull files from Weights & Biases")
@click.argument("run", envvar='WANDB_RUN')
@click.option("--project", "-p", envvar='WANDB_PROJECT', help="The project you want to download.")
@click.option("--entity", "-e", default="models", envvar='WANDB_ENTITY', help="The entity to scope the listing to.")
@display_error
def pull(project, run, entity):
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
            with click.progressbar(length=length, label='File %s' % name,
                                   fill_char=click.style('&', fg='green')) as bar:
                with open(name, "wb") as f:
                    for data in response.iter_content(chunk_size=4096):
                        f.write(data)
                        bar.update(len(data))


@cli.command(context_settings=CONTEXT, help="Login to Weights & Biases")
@display_error
def login():
    # Import in here for performance reasons
    import webbrowser
    # TODO: use Oauth and a local webserver: https://community.auth0.com/questions/6501/authenticating-an-installed-cli-with-oidc-and-a-th
    url = api.app_url + '/profile?message=true'
    # TODO: google cloud SDK check_browser.py
    launched = webbrowser.open_new_tab(url)
    if launched:
        click.echo(
            'Opening [{0}] in a new tab in your default browser.'.format(url))
    else:
        click.echo("You can find your API keys here: {0}".format(url))

    key = click.prompt("{warning} Paste an API key from your profile".format(
        warning=click.style("Not authenticated!", fg="red")),
        value_proc=lambda x: x.strip())

    if key:
        # TODO: get the username here...
        # username = api.viewer().get('entity', 'models')
        write_netrc(api.api_url, "user", key)


@cli.command(context_settings=CONTEXT, help="Configure a directory with Weights & Biases")
@click.pass_context
@display_error
def init(ctx):
    from wandb import _set_stage_dir, wandb_dir
    if wandb_dir() is None:
        _set_stage_dir('wandb')
    wandb_path = os.path.join(os.getcwd(), wandb_dir())
    if os.path.isdir(wandb_path):
        click.confirm(click.style(
            "This directory has been configured previously, should we re-configure it?", bold=True), abort=True)
    else:
        click.echo(click.style(
            "Let's setup this directory for W&B!", fg="green", bold=True))

    global api, IS_INIT

    if api.api_key is None:
        ctx.invoke(login)
        api = Api()

    IS_INIT = True

    viewer = api.viewer()
    if len(viewer["teams"]["edges"]) > 1:
        team_names = [e["node"]["name"] for e in viewer["teams"]["edges"]]
        question = {
            'type': 'list',
            'name': 'team_name',
            'message': "Which team should we use?",
            'choices': team_names + ["Manual Entry"]
        }
        entity = whaaaaat.prompt([question])['team_name']
        if entity == "Manual Entry":
            entity = click.prompt("Enter the name of the team you want to use")
    else:
        entity = click.prompt("What username or team should we use?",
                              default=viewer.get('entity', 'models'))

    # TODO: this error handling sucks and the output isn't pretty
    try:
        project = prompt_for_project(ctx, entity)
    except wandb.cli.ClickWandbException:
        raise ClickException('Could not find team: %s' % entity)

    if not os.path.isdir(wandb_path):
        os.mkdir(wandb_path)

    with open(os.path.join(wandb_dir(), 'settings'), "w") as file:
        print('[default]', file=file)
        print('entity: {}'.format(entity), file=file)
        print('project: {}'.format(project), file=file)
        print('base_url: {}'.format(api.settings()['base_url']), file=file)

    with open(os.path.join(wandb_dir(), '.gitignore'), "w") as file:
        file.write("*\n!settings")

    config_defaults_path = 'config-defaults.yaml'
    if not os.path.exists(config_defaults_path):
        with open(config_defaults_path, 'w') as file:
            file.write(textwrap.dedent("""\
                wandb_version: 1

                # Example variables below. Uncomment (remove leading '# ') to use them, or just
                # delete and create your own.

                # epochs:
                #   desc: Number of epochs to train over
                #   value: 100
                # batch_size:
                #   desc: Size of each mini-batch
                #   value: 32
                """))

    click.echo(click.style("This directory is configured!  Next, track a run:\n", fg="green") +
               textwrap.dedent("""\
        * In your training script:
            {code1}
            {code2}
        * then `{run}`.
        """).format(
        code1=click.style("import wandb", bold=True),
        code2=click.style("wandb.init()", bold=True),
        run=click.style("wandb run <train.py>", bold=True),
        # saving this here so I can easily put it back when we re-enable
        # push/pull
        #"""
        #* Run `{push}` to manually add a file.
        #* Pull popular models into your project with: `{pull}`.
        #"""
        # push=click.style("wandb push run_id weights.h5", bold=True),
        # pull=click.style("wandb pull models/inception-v4", bold=True)
    ))


@cli.command(context_settings=CONTEXT, help="Open documentation in a browser")
@click.pass_context
@display_error
def docs(ctx):
    import webbrowser
    launched = webbrowser.open_new_tab(DOCS_URL)
    if launched:
        click.echo(click.style(
            "Opening %s in your default browser" % DOCS_URL, fg="green"))
    else:
        click.echo(click.style(
            "You can find our documentation here: %s" % DOCS_URL, fg="green"))


RUN_CONTEXT = copy.copy(CONTEXT)
RUN_CONTEXT['allow_extra_args'] = True
RUN_CONTEXT['ignore_unknown_options'] = True


@cli.command(context_settings=RUN_CONTEXT, help="Launch a job")
@click.pass_context
@require_init
@click.argument('program')
@click.argument('args', nargs=-1)
@click.option('--id', default=None,
              help='Run id to use, default is to generate.')
@click.option('--dir', default=None,
              help='Files in this directory will be saved to wandb, defaults to wandb')
@click.option('--configs', default=None,
              help='Config file paths to load')
@click.option('--message', '-m', default=None,
              help='Message to associate with the run.')
@click.option("--show/--no-show", default=False,
              help="Open the run page in your default browser.")
@display_error
def run(ctx, program, args, id, dir, configs, message, show):
    api.ensure_configured()
    if configs:
        config_paths = configs.split(',')
    else:
        config_paths = []
    config = Config(config_paths=config_paths,
                    wandb_dir=dir or wandb.wandb_dir())
    run = wandb_run.Run(run_id=id, mode='run',
                        config=config, description=message)

    api.set_current_run_id(run.id)

    # TODO: better failure handling
    root = api.git.root
    remote_url = api.git.remote_url
    host = socket.gethostname()
    # handle non-git directories
    if not root:
        root = os.path.abspath(os.getcwd())
        remote_url = 'file://%s%s' % (host, root)

    upsert_result = api.upsert_run(name=run.id,
                                   project=api.settings("project"),
                                   entity=api.settings("entity"),
                                   config=run.config.as_dict(), description=run.description, host=host,
                                   program_path=program, repo=remote_url, sweep_name=run.sweep_id)
    run.storage_id = upsert_result['id']
    env = dict(os.environ)
    run.set_environment(env)
    if configs:
        env['WANDB_CONFIG_PATHS'] = configs
    if show:
        env['WANDB_SHOW_RUN'] = 'True'

    try:
        rm = run_manager.RunManager(api, run, program=program)
    except run_manager.Error:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        wandb.termerror('An Exception was raised during setup, see %s for full traceback.' %
                        util.get_log_file_path())
        wandb.termerror(exc_value)
        if 'permission' in str(exc_value):
            wandb.termerror(
                'Are you sure you provided the correct API key to "wandb login"?')
        lines = traceback.format_exception(
            exc_type, exc_value, exc_traceback)
        logger.error('\n'.join(lines))
        return

    rm.run_user_process(program, args, env)


@cli.command(context_settings=CONTEXT, help="Create a sweep")
@click.pass_context
@require_init
@click.argument('config_yaml')
@display_error
def sweep(ctx, config_yaml):
    click.echo('Creating sweep from: %s' % config_yaml)
    try:
        yaml_file = open(config_yaml)
    except OSError:
        wandb.termerror('Couldn\'t open sweep file: %s' % config_yaml)
        return
    try:
        config = yaml.load(yaml_file)
    except yaml.YAMLError as err:
        wandb.termerror('Error in configuration file: %s' % err)
        return
    if config is None:
        wandb.termerror('Configuration file is empty')
        return
    sweep_id = api.upsert_sweep(config)
    print('Create sweep with ID:', sweep_id)


@cli.command(context_settings=CONTEXT, help="Run the WandB agent")
@click.argument('sweep_id')
@require_init
@display_error
def agent(sweep_id):
    click.echo('Starting wandb agent 🕵️')
    wandb_agent.run_agent(sweep_id)

    # you can send local commands like so:
    # agent_api.command({'type': 'run', 'program': 'train.py',
    #                'args': ['--max_epochs=10']})


@cli.command(context_settings=CONTEXT, help="Start a local WandB Board server")
@click.option('--port', '-p', default=7177,
              help='The port to start the server on')
@click.option('--host', '-h', default="localhost",
              help='The host to bind to')
@click.option('--logdir', default=".",
              help='The directory to find wandb logs')
@display_error
def board(port, host, logdir):
    import webbrowser
    import werkzeug.serving
    path = os.path.abspath(logdir) if logdir != "." else None
    if path and os.path.exists(path + "/wandb"):
        path = path + "/wandb"
    from wandb.board import create_app, data
    app = create_app("default", path)
    if len(data['Runs']) == 0:
        raise ClickException(
            "No runs found in this directory, specify a different directory with --logdir")
    dev = os.getenv('WANDB_ENV', "").startswith("dev")
    extra = "(dev)" if dev else ""
    if not werkzeug.serving.is_running_from_reloader():
        click.echo(
            'Started wandb board on http://{0}:{1} ✨ {2}'.format(host, port, extra))
        threading.Timer(1, webbrowser.open_new_tab,
                        ("http://{0}:{1}".format(host, port),)).start()
    elif dev:
        click.echo("Reloading backend...")
    app.run(host, port, threaded=True, debug=dev)


if __name__ == "__main__":
    cli()
