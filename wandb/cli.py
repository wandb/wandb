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
import random

from wandb import util


from click.utils import LazyFile
from click.exceptions import BadParameter, ClickException, Abort
# whaaaaat depends on prompt_toolkit < 2, ipython now uses > 2 so we vendored for now
# DANGER this changes the sys.path so we should never do this in a user script
whaaaaat = util.vendor_import("whaaaaat")
from six.moves import BaseHTTPServer, urllib, configparser
import socket

from .core import termlog

import wandb
from wandb.apis import InternalApi
from wandb.wandb_config import Config
from wandb import agent as wandb_agent
from wandb import env
from wandb import wandb_run
from wandb import wandb_dir
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


class CallbackHandler(BaseHTTPServer.BaseHTTPRequestHandler):
    """Simple callback handler that stores query string parameters and 
    shuts down the server.
    """

    def do_GET(self):
        self.server.result = urllib.parse.parse_qs(
            self.path.split("?")[-1])
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'Success')
        self.server.stop()


class LocalServer():
    """A local HTTP server that finds an open port and listens for a callback.
    The urlencoded callback url is accessed via `.qs` the query parameters passed
    to the callback are accessed via `.result`
    """

    def __init__(self):
        self.blocking = True
        self.port = 8666
        self.connect()
        self._server.result = {}
        self._server.stop = self.stop

    def connect(self, attempts=1):
        try:
            self._server = BaseHTTPServer.HTTPServer(
                ('127.0.0.1', self.port), CallbackHandler)
        except socket.error:
            if attempts < 5:
                self.port += random.randint(1, 1000)
                self.connect(attempts + 1)
            else:
                logging.info(
                    "Unable to start local server, proceeding manually")

                class FakeServer():
                    def serve_forever(self):
                        pass
                self._server = FakeServer()

    def qs(self):
        return urllib.parse.urlencode({
            "callback": "http://127.0.0.1:{}/callback".format(self.port)})

    @property
    def result(self):
        return self._server.result

    def start(self, blocking=True):
        self.blocking = blocking
        if self.blocking:
            self._server.serve_forever()
        else:
            t = threading.Thread(target=self._server.serve_forever)
            t.daemon = True
            t.start()

    def stop(self, *args):
        t = threading.Thread(target=self._server.shutdown)
        t.daemon = True
        t.start()
        if not self.blocking:
            os.kill(os.getpid(), signal.SIGINT)


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
            result = whaaaaat.prompt([question])
            if result:
                project = result['project_name']
            else:
                project = "Create New"
            # TODO: check with the server if the project exists
            if project == "Create New":
                project = click.prompt(
                    "Enter a name for your new project", value_proc=api.format_project)
                #description = editor()
                project = api.upsert_project(project, entity=entity)["name"]

    except wandb.apis.CommError as e:
        raise ClickException(str(e))

    return project


def editor(content='', marker='# Enter a description, markdown is allowed!\n'):
    message = click.edit(content + '\n\n' + marker)
    if message is not None:
        return message.split(marker, 1)[0].rstrip('\n')


api = InternalApi()


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


@click.command(cls=RunGroup, invoke_without_command=True)
@click.version_option(version=wandb.__version__)
@click.pass_context
def cli(ctx):
    """Weights & Biases.

    Run "wandb docs" for full documentation.
    """
    wandb.try_to_set_up_global_logging()
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@cli.command(context_settings=CONTEXT, help="List projects")
@require_init
@click.option("--entity", "-e", default=None, envvar=env.ENTITY, help="The entity to scope the listing to.")
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
@click.option("--project", "-p", default=None, envvar=env.PROJECT, help="The project you wish to list runs from.")
@click.option("--entity", "-e", default=None, envvar=env.ENTITY, help="The entity to scope the listing to.")
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
@click.argument("run", envvar=env.RUN)
@click.option("--settings/--no-settings", help="Show the current settings", default=True)
@click.option("--project", "-p", envvar=env.PROJECT, help="The project you wish to upload to.")
@display_error
def status(run, settings, project):
    logged_in = bool(api.api_key)
    if not os.path.isdir(wandb_dir()):
        if logged_in:
            msg = "Directory not initialized. Please run %s to get started." % click.style(
                "wandb init", bold=True)
        else:
            msg = "You are not logged in. Please run %s to get started." % click.style(
                "wandb login", bold=True)
        termlog(msg)
    elif settings:
        click.echo(click.style("Logged in?", bold=True) + " %s" % logged_in)
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
@click.argument("run", envvar=env.RUN)
@click.option("--branch/--no-branch", default=True, help="Whether to create a branch or checkout detached")
@click.option("--project", "-p", envvar=env.PROJECT, help="The project you wish to upload to.")
@click.option("--entity", "-e", default="models", envvar=env.ENTITY, help="The entity to scope the listing to.")
@display_error
def restore(run, branch, project, entity):
    if not api.git.enabled:
        raise ClickException("`wandb restore` can only be called from within an existing git repository.")
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
                raise ClickException("Can't find commit from which to restore code")
        else:
            if patch_content:
                patch_path = os.path.join(wandb.wandb_dir(), 'diff.patch')
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
@click.argument("run", envvar=env.RUN)
@click.option("--project", "-p", envvar=env.PROJECT, help="The project you want to download.")
@click.option("--entity", "-e", default="models", envvar=env.ENTITY, help="The entity to scope the listing to.")
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
            # TODO: I had to add this because some versions in CI broke click.progressbar
            sys.stdout.write("File %s\r" % name)
            with click.progressbar(length=length, label='File %s' % name,
                                   fill_char=click.style('&', fg='green')) as bar:
                with open(name, "wb") as f:
                    for data in response.iter_content(chunk_size=4096):
                        f.write(data)
                        bar.update(len(data))


@cli.command(context_settings=CONTEXT, help="Signup for Weights & Biases")
@click.pass_context
@display_error
def signup(ctx):
    import webbrowser
    server = LocalServer()
    url = api.app_url + "/login?signup=true"
    if util.launch_browser():
        launched = webbrowser.open_new_tab(
            url + "&{}".format(server.qs()))
    else:
        launched = False
    if launched:
        signal.signal(signal.SIGINT, server.stop)
        click.echo(
            'Opened [{0}] in your default browser'.format(url))
        server.start(blocking=False)
    else:
        click.echo("Signup with this url in your browser: {0}".format(url))
    key = ctx.invoke(login, server=server, browser=False)
    if key:
        # Only init if we aren't pre-configured
        if not os.path.isdir(wandb_dir()):
            ctx.invoke(init)


@cli.command(context_settings=CONTEXT, help="Login to Weights & Biases")
@click.argument("key", nargs=-1)
@click.option("--browser/--no-browser", default=True, help="Attempt to launch a browser for login")
@display_error
def login(key, server=LocalServer(), browser=True):
    global api

    key = key[0] if len(key) > 0 else None
    # Import in here for performance reasons
    import webbrowser
    # TODO: use Oauth?: https://community.auth0.com/questions/6501/authenticating-an-installed-cli-with-oidc-and-a-th
    url = api.app_url + '/profile?message=key'
    browser = util.launch_browser(browser)
    if key or not browser:
        launched = False
    else:
        launched = webbrowser.open_new_tab(url + "&{}".format(server.qs()))
    if launched:
        click.echo(
            'Opening [{0}] in your default browser'.format(url))
        server.start(blocking=False)
    elif not key and browser:
        click.echo(
            "You can find your API keys in your browser here: {0}".format(url))

    def cancel_prompt(*args):
        raise KeyboardInterrupt()
    # Hijacking this signal broke tests in py2...
    # if not os.getenv("WANDB_TEST"):
    signal.signal(signal.SIGINT, cancel_prompt)
    try:
        key = key or click.prompt("Paste an API key from your profile",
                                  value_proc=lambda x: x.strip())
    except Abort:
        if server.result.get("key"):
            key = server.result["key"][0]

    if key:
        # TODO: get the username here...
        # username = api.viewer().get('entity', 'models')
        if util.write_netrc(api.api_url, "user", key):
            click.secho(
                "Successfully logged in to Weights & Biases!", fg="green")
    else:
        click.echo("No key provided, please try again")

    # reinitialize API to create the new client
    api = InternalApi()

    return key


@cli.command(context_settings=CONTEXT, help="Configure a directory with Weights & Biases")
@click.pass_context
@display_error
def init(ctx):
    from wandb import _set_stage_dir, __stage_dir__, wandb_dir
    if __stage_dir__ is None:
        _set_stage_dir('wandb')
    if os.path.isdir(wandb_dir()):
        click.confirm(click.style(
            "This directory has been configured previously, should we re-configure it?", bold=True), abort=True)
    else:
        click.echo(click.style(
            "Let's setup this directory for W&B!", fg="green", bold=True))

    global IS_INIT

    if api.api_key is None:
        ctx.invoke(login)

    IS_INIT = True

    viewer = api.viewer()

    # Viewer can be `None` in case your API information became invalid, or
    # in testing if you switch hosts.
    if not viewer:
        click.echo(click.style(
            "Your login information seems to be invalid: can you log in again please?", fg="red", bold=True))
        ctx.invoke(login)

    # This shouldn't happen.
    viewer = api.viewer()
    if not viewer:
        click.echo(click.style(
            "We're sorry, there was a problem logging you in. Please send us a note at support@wandb.com and tell us how this happened.", fg="red", bold=True))
        sys.exit(1)

    # At this point we should be logged in successfully.
    if len(viewer["teams"]["edges"]) > 1:
        team_names = [e["node"]["name"] for e in viewer["teams"]["edges"]]
        question = {
            'type': 'list',
            'name': 'team_name',
            'message': "Which team should we use?",
            'choices': team_names + ["Manual Entry"]
        }
        result = whaaaaat.prompt([question])
        # result can be empty on click
        if result:
            entity = result['team_name']
        else:
            entity = "Manual Entry"
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

    util.write_settings(entity, project, api.settings()['base_url'])

    with open(os.path.join(wandb_dir(), '.gitignore'), "w") as file:
        file.write("*\n!settings")

    click.echo(click.style("This directory is configured!  Next, track a run:\n", fg="green") +
               textwrap.dedent("""\
        * In your training script:
            {code1}
            {code2}
        * then `{run}`.
        """).format(
        code1=click.style("import wandb", bold=True),
        code2=click.style("wandb.init()", bold=True),
        run=click.style("python <train.py>", bold=True),
        # saving this here so I can easily put it back when we re-enable
        # push/pull
        #"""
        #* Run `{push}` to manually add a file.
        #* Pull popular models into your project with: `{pull}`.
        #"""
        # push=click.style("wandb push run_id weights.h5", bold=True),
        # pull=click.style("wandb pull models/inception-v4", bold=True)
    ))


# @cli.group()
# def config():
#     """Manage this project's configuration."""
#     pass


# @config.command("init", help="Initialize a directory with wandb configuration")
# @display_error
# def config_init():
#     config_defaults_path = 'config-defaults.yaml'
#     if not os.path.exists(config_defaults_path):
#         with open(config_defaults_path, 'w') as file:
#             file.write(textwrap.dedent("""\
#                 wandb_version: 1

#                 # Example variables below. Uncomment (remove leading '# ') to use them, or just
#                 # delete and create your own.

#                 # epochs:
#                 #   desc: Number of epochs to train over
#                 #   value: 100
#                 # batch_size:
#                 #   desc: Size of each mini-batch
#                 #   value: 32
#                 """))
#     click.echo(
#         "Edit config-defaults.yaml with your default configuration parameters.")


@cli.command(context_settings=CONTEXT, help="Open documentation in a browser")
@click.pass_context
@display_error
def docs(ctx):
    import webbrowser
    if util.launch_browser():
        launched = webbrowser.open_new_tab(DOCS_URL)
    else:
        launched = False
    if launched:
        click.echo(click.style(
            "Opening %s in your default browser" % DOCS_URL, fg="green"))
    else:
        click.echo(click.style(
            "You can find our documentation here: %s" % DOCS_URL, fg="green"))


@cli.command("on", help="Ensure W&B is enabled in this directory")
@display_error
def on():
    wandb.ensure_configured()
    api = InternalApi()
    parser = api.settings_parser
    try:
        parser.remove_option('default', 'disabled')
        with open(api.settings_file, "w") as f:
            parser.write(f)
    except configparser.Error:
        pass
    click.echo(
        "W&B enabled, running your script from this directory will now sync to the cloud.")


@cli.command("off", help="Disable W&B in this directory, useful for testing")
@display_error
def off():
    wandb.ensure_configured()
    api = InternalApi()
    parser = api.settings_parser
    try:
        parser.set('default', 'disabled', 'true')
        with open(api.settings_file, "w") as f:
            parser.write(f)
        click.echo(
            "W&B disabled, running your script from this directory will only write metadata locally.")
    except configparser.Error as e:
        click.echo(
            'Unable to write config, copy and paste the following in your terminal to turn off W&B:\nexport WANDB_MODE=dryrun')


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
@click.option('--resume', default='never', type=click.Choice(['never', 'must', 'allow']),
              help='Resume strategy, default is never')
@click.option('--dir', default=None,
              help='Files in this directory will be saved to wandb, defaults to wandb')
@click.option('--configs', default=None,
              help='Config file paths to load')
@click.option('--message', '-m', default=None,
              help='Message to associate with the run.')
@click.option("--show/--no-show", default=False,
              help="Open the run page in your default browser.")
@display_error
def run(ctx, program, args, id, resume, dir, configs, message, show):
    wandb.ensure_configured()
    if configs:
        config_paths = configs.split(',')
    else:
        config_paths = []
    config = Config(config_paths=config_paths,
                    wandb_dir=dir or wandb.wandb_dir())
    run = wandb_run.Run(run_id=id, mode='clirun',
                        config=config, description=message,
                        program=program,
                        resume=resume)
    run.enable_logging()

    api.set_current_run_id(run.id)

    environ = dict(os.environ)
    if configs:
        environ[env.CONFIG_PATHS] = configs
    if show:
        environ[env.SHOW_RUN] = 'True'

    try:
        rm = run_manager.RunManager(api, run)
        rm.init_run(environ)
    except run_manager.Error:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        wandb.termerror('An Exception was raised during setup, see %s for full traceback.' %
                        util.get_log_file_path())
        wandb.termerror(str(exc_value))
        if 'permission' in str(exc_value):
            wandb.termerror(
                'Are you sure you provided the correct API key to "wandb login"?')
        lines = traceback.format_exception(
            exc_type, exc_value, exc_traceback)
        logger.error('\n'.join(lines))
        sys.exit(1)

    rm.run_user_process(program, args, environ)


# @cli.command(context_settings=CONTEXT, help="Create a sweep")
# @click.pass_context
# @require_init
# @click.argument('config_yaml')
# @display_error
# def sweep(ctx, config_yaml):
#     click.echo('Creating sweep from: %s' % config_yaml)
#     try:
#         yaml_file = open(config_yaml)
#     except (OSError, IOError):
#         wandb.termerror('Couldn\'t open sweep file: %s' % config_yaml)
#         return
#     try:
#         config = yaml.load(yaml_file)
#     except yaml.YAMLError as err:
#         wandb.termerror('Error in configuration file: %s' % err)
#         return
#     if config is None:
#         wandb.termerror('Configuration file is empty')
#         return
#     sweep_id = api.upsert_sweep(config)
#     print('Create sweep with ID:', sweep_id)


# @cli.command(context_settings=CONTEXT, help="Run the WandB agent")
# @click.argument('sweep_id')
# @require_init
# @display_error
# def agent(sweep_id):
#     click.echo('Starting wandb agent 🕵️')
#     wandb_agent.run_agent(sweep_id)

#     # you can send local commands like so:
#     # agent_api.command({'type': 'run', 'program': 'train.py',
#     #                'args': ['--max_epochs=10']})


if __name__ == "__main__":
    cli()
