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
import platform
import datetime
import shutil
import getpass
# pycreds has a find_executable that works in windows
from dockerpycreds.utils import find_executable

from wandb import util

from click.utils import LazyFile
from click.exceptions import BadParameter, ClickException, Abort
# whaaaaat depends on prompt_toolkit < 2, ipython now uses > 2 so we vendored for now
# DANGER this changes the sys.path so we should never do this in a user script
whaaaaat = util.vendor_import("whaaaaat")
import six
from six.moves import BaseHTTPServer, urllib, configparser
import socket

from .core import termlog

import wandb
from wandb.apis import InternalApi
from wandb.wandb_config import Config
from wandb.settings import Settings
from wandb import wandb_agent
from wandb import wandb_controller
from wandb import env
from wandb import wandb_run
from wandb import wandb_dir
from wandb import run_manager
from wandb import Error
from wandb.magic_impl import magic_install

DOCS_URL = 'http://docs.wandb.com/'
logger = logging.getLogger(__name__)


class ClickWandbException(ClickException):
    def format_message(self):
        log_file = util.get_log_file_path()
        orig_type = '{}.{}'.format(self.orig_type.__module__,
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

    def log_message(self, format, *args):
        pass


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
            six.reraise(ClickWandbException, click_exc, sys.exc_info()[2])
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
@click.argument("run", envvar=env.RUN_ID)
@click.option("--settings/--no-settings", help="Show the current settings", default=True)
@display_error
def status(run, settings):
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
        click.echo(click.style("Current Settings", bold=True))
        settings = api.settings()
        click.echo(json.dumps(
            settings,
            sort_keys=True,
            indent=2,
            separators=(',', ': ')
        ))


@cli.command(context_settings=CONTEXT, help="Restore code, config and docker state for a run")
@click.pass_context
@click.argument("run", envvar=env.RUN_ID)
@click.option("--no-git", is_flag=True, default=False, help="Skupp")
@click.option("--branch/--no-branch", default=True, help="Whether to create a branch or checkout detached")
@click.option("--project", "-p", envvar=env.PROJECT, help="The project you wish to upload to.")
@click.option("--entity", "-e", envvar=env.ENTITY, help="The entity to scope the listing to.")
@display_error
def restore(ctx, run, no_git, branch, project, entity):
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
        project, run=run, entity=entity)
    repo = metadata.get("git", {}).get("repo")
    image = metadata.get("docker")
    RESTORE_MESSAGE = """`wandb restore` needs to be run from the same git repository as the original run.
Run `git clone %s` and restore from there or pass the --no-git flag.""" % repo
    if no_git:
        commit = None
    elif not api.git.enabled:
        if repo:
            raise ClickException(RESTORE_MESSAGE)
        elif image:
            wandb.termlog("Original run has no git history.  Just restoring config and docker")

    if commit and api.git.enabled:
        subprocess.check_call(['git', 'fetch', '--all'])
        try:
            api.git.repo.commit(commit)
        except ValueError:
            wandb.termlog("Couldn't find original commit: {}".format(commit))
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
                wandb.termlog(
                    "Falling back to upstream commit: {}".format(commit))
                patch_path, _ = api.download_write_file(files[filename])
            else:
                raise ClickException(RESTORE_MESSAGE)
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
            wandb.termlog("Created branch %s" %
                       click.style(branch_name, bold=True))
        elif branch:
            wandb.termlog(
                "Using existing branch, run `git branch -D %s` from master for a clean checkout" % branch_name)
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
            # we use .call() instead of .check_call() for the same reason
            # TODO(adrian): this means there is no error checking here
            subprocess.call(['git', 'apply', '--reject',
                             patch_rel_path], cwd=root)
            wandb.termlog("Applied patch")

    # TODO: we should likely respect WANDB_DIR here.
    util.mkdir_exists_ok("wandb")
    config = Config(run_dir="wandb")
    config.load_json(json_config)
    config.persist()
    wandb.termlog("Restored config variables to %s" % config._config_path())
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


@cli.command(context_settings=CONTEXT, help="Upload an offline training directory to W&B")
@click.pass_context
@click.argument("path", nargs=-1, type=click.Path(exists=True))
@click.option("--id", envvar=env.RUN_ID, help="The run you want to upload to.")
@click.option("--project", "-p", envvar=env.PROJECT, help="The project you want to upload to.")
@click.option("--entity", "-e", envvar=env.ENTITY, help="The entity to scope to.")
@click.option("--ignore", help="A comma seperated list of globs to ignore syncing with wandb.")
@display_error
def sync(ctx, path, id, project, entity, ignore):
    if api.api_key is None:
        ctx.invoke(login)

    if ignore:
        globs = ignore.split(",")
    else:
        globs = None

    path = path[0] if len(path) > 0 else os.getcwd()
    if os.path.isfile(path):
        raise ClickException("path must be a directory")
    wandb_dir = os.path.join(path, "wandb")
    run_paths = glob.glob(os.path.join(wandb_dir, "*run-*"))
    if len(run_paths) == 0:
        run_paths = glob.glob(os.path.join(path, "*run-*"))
    if len(run_paths) > 0:
        for run_path in run_paths:
            wandb_run.Run.from_directory(run_path,
                                         run_id=run_path.split("-")[-1], project=project, entity=entity, ignore_globs=globs)
    else:
        wandb_run.Run.from_directory(
            path, run_id=id, project=project, entity=entity, ignore_globs=globs)


@cli.command(context_settings=CONTEXT, help="Pull files from Weights & Biases")
@click.argument("run", envvar=env.RUN_ID)
@click.option("--project", "-p", envvar=env.PROJECT, help="The project you want to download.")
@click.option("--entity", "-e", default="models", envvar=env.ENTITY, help="The entity to scope the listing to.")
@display_error
def pull(run, project, entity):
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


@cli.command(context_settings=CONTEXT, help="Login to Weights & Biases")
@click.argument("key", nargs=-1)
@click.option("--cloud", is_flag=True, help="Login to the cloud instead of local")
@click.option("--host", default=None, help="Login to a specific instance of W&B")
@click.option("--browser/--no-browser", default=True, help="Attempt to launch a browser for login")
@click.option("--anonymously", is_flag=True, help="Log in anonymously")
@display_error
def login(key, cloud, host, anonymously, server=LocalServer(), browser=True, no_offline=False):
    global api
    if host == "https://api.wandb.ai" or (host is None and cloud):
        api.clear_setting("base_url", globally=True, persist=True)
        # To avoid writing an empty local settings file, we only clear if it exists
        if os.path.exists(Settings._local_path()):
            api.clear_setting("base_url", persist=True)
    elif host:
        if not host.startswith("http"):
            raise ClickException("host must start with http(s)://")
        api.set_setting("base_url", host.strip("/"), globally=True, persist=True)

    key = key[0] if len(key) > 0 else None

    # Import in here for performance reasons
    import webbrowser
    browser = util.launch_browser(browser)

    def get_api_key_from_browser(signup=False):
        if not browser:
            return None
        query = '?signup=true' if signup else ''
        webbrowser.open_new_tab('{}/authorize{}'.format(api.app_url, query))
        #Getting rid of the server for now.  We would need to catch Abort from server.stop and deal accordingly
        #server.start(blocking=False)
        #if server.result.get("key"):
        #    return server.result["key"][0]
        return None

    if key:
        util.set_api_key(api, key)
    else:
        if anonymously:
            os.environ[env.ANONYMOUS] = "must"
        # Don't allow signups or dryrun for local
        local = host != None or host != "https://api.wandb.ai"
        key = util.prompt_api_key(api, input_callback=click.prompt,
            browser_callback=get_api_key_from_browser, no_offline=no_offline, local=local)

    if key:
        api.clear_setting('disabled', persist=True)
        click.secho("Successfully logged in to Weights & Biases!", fg="green")
    elif not no_offline:
        api.set_setting('disabled', 'true', persist=True)
        click.echo("Disabling Weights & Biases. Run 'wandb login' again to re-enable.")

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
    if os.path.isdir(wandb_dir()) and os.path.exists(os.path.join(wandb_dir(), "settings")):
        click.confirm(click.style(
            "This directory has been configured previously, should we re-configure it?", bold=True), abort=True)
    else:
        click.echo(click.style(
            "Let's setup this directory for W&B!", fg="green", bold=True))

    if api.api_key is None:
        ctx.invoke(login)

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

    api.set_setting('entity', entity, persist=True)
    api.set_setting('project', project, persist=True)
    api.set_setting('base_url', api.settings().get('base_url'), persist=True)

    util.mkdir_exists_ok(wandb_dir())
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
        code2=click.style("wandb.init(project=\"%s\")" % project, bold=True),
        run=click.style("python <train.py>", bold=True),
        # saving this here so I can easily put it back when we re-enable
        # push/pull
        # """
        # * Run `{push}` to manually add a file.
        # * Pull popular models into your project with: `{pull}`.
        # """
        # push=click.style("wandb push run_id weights.h5", bold=True),
        # pull=click.style("wandb pull models/inception-v4", bold=True)
    ))


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
    try:
        api.clear_setting('disabled', persist=True)
    except configparser.Error:
        pass
    click.echo(
        "W&B enabled, running your script from this directory will now sync to the cloud.")


@cli.command("off", help="Disable W&B in this directory, useful for testing")
@display_error
def off():
    wandb.ensure_configured()
    api = InternalApi()
    try:
        api.set_setting('disabled', 'true', persist=True)
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
@click.option('--message', '-m', default=None, hidden=True,
              help='Message to associate with the run.')
@click.option('--name', default=None,
              help='Name of the run, default is auto generated.')
@click.option('--notes', default=None,
              help='Notes to associate with the run.')
@click.option("--show/--no-show", default=False,
              help="Open the run page in your default browser.")
@click.option('--tags', default=None,
              help='Tags to associate with the run (comma seperated).')
@click.option('--run_group', default=None,
              help='Run group to associate with the run.')
@click.option('--job_type', default=None,
              help='Job type to associate with the run.')
@display_error
def run(ctx, program, args, id, resume, dir, configs, message, name, notes, show, tags, run_group, job_type):
    wandb.ensure_configured()
    if configs:
        config_paths = configs.split(',')
    else:
        config_paths = []
    config = Config(config_paths=config_paths,
                    wandb_dir=dir or wandb.wandb_dir())
    tags = [tag for tag in tags.split(",") if tag] if tags else None

    # populate run parameters from env if not specified
    id = id or os.environ.get(env.RUN_ID)
    message = message or os.environ.get(env.DESCRIPTION)
    tags = tags or env.get_tags()
    run_group = run_group or os.environ.get(env.RUN_GROUP)
    job_type = job_type or os.environ.get(env.JOB_TYPE)
    name = name or os.environ.get(env.NAME)
    notes = notes or os.environ.get(env.NOTES)
    resume = resume or os.environ.get(env.RESUME)

    run = wandb_run.Run(run_id=id, mode='clirun',
                        config=config, description=message,
                        program=program, tags=tags,
                        group=run_group, job_type=job_type,
                        name=name, notes=notes,
                        resume=resume)
    run.enable_logging()

    environ = dict(os.environ)
    if configs:
        environ[env.CONFIG_PATHS] = configs
    if show:
        environ[env.SHOW_RUN] = 'True'

    if not run.api.api_key:
        util.prompt_api_key(run.api, input_callback=click.prompt)

    try:
        rm = run_manager.RunManager(run)
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

@cli.command(context_settings=RUN_CONTEXT, help="Launch local W&B container (Experimental)")
@click.pass_context
@click.option('--port', '-p', default="8080", help="The host port to bind W&B local on")
@click.option('--env', '-e', default=[], multiple=True, help="Env vars to pass to wandb/local")
@click.option('--daemon/--no-daemon', default=True, help="Run or don't run in daemon mode")
@click.option('--upgrade', is_flag=True, default=False, help="Upgrade to the most recent version")
@click.option('--edge', is_flag=True, default=False, help="Run the bleading edge", hidden=True)
@display_error
def local(ctx, port, env, daemon, upgrade, edge):
    if not find_executable('docker'):
        raise ClickException(
            "Docker not installed, install it from https://docker.com" )
    if wandb.docker.image_id("wandb/local") != wandb.docker.image_id_from_registry("wandb/local"):
        if upgrade:
            subprocess.call(["docker", "pull", "wandb/local"])
        else:
            wandb.termlog("A new version of W&B local is available, upgrade by calling `wandb local --upgrade`")
    running = subprocess.check_output(["docker", "ps", "--filter", "name=wandb-local", "--format", "{{.ID}}"])
    if running != b"":
        if upgrade:
            subprocess.call(["docker", "stop", "wandb-local"])
        else:
            wandb.termerror("A container named wandb-local is already running, run `docker stop wandb-local` if you want to start a new instance")
            exit(1)
    image = "docker.pkg.github.com/wandb/core/local" if edge else "wandb/local"
    username = getpass.getuser()
    env_vars = ['-e', 'LOCAL_USERNAME=%s' % username]
    for e in env:
        env_vars.append('-e')
        env_vars.append(e)
    command = ['docker', 'run', '--rm', '-v', 'wandb:/vol', '-p', port+':8080', '--name', 'wandb-local'] + env_vars
    host = "http://localhost:%s" % port
    api.set_setting("base_url", host, globally=True, persist=True)
    if daemon:
        command += ["-d"]
    command += [image]

    # DEVNULL is only in py3
    try:
        from subprocess import DEVNULL
    except ImportError:
        DEVNULL = open(os.devnull, 'wb')
    code = subprocess.call(command, stdout=DEVNULL)
    if daemon:
        if code != 0:
            wandb.termerror("Failed to launch the W&B local container, see the above error.")
            exit(1)
        else:
            wandb.termlog("W&B local started at http://localhost:%s \U0001F680" % port)
            wandb.termlog("You can stop the server by running `docker stop wandb-local`")
            if not api.api_key:
                # Let the server start before potentially launching a browser
                time.sleep(2)
                ctx.invoke(login, host=host)

@cli.command(context_settings=RUN_CONTEXT)
@click.pass_context
@click.option('--keep', '-N', default=24, help="Keep runs created in the last N hours", type=int)
def gc(ctx, keep):
    """Garbage collector, cleans up your local run directory"""
    directory = wandb.wandb_dir()
    if not os.path.exists(directory):
        raise ClickException('No wandb directory found at %s' % directory)
    paths = glob.glob(directory+"/*run*")
    dates = [datetime.datetime.strptime(p.split("-")[1],'%Y%m%d_%H%M%S') for p in paths]
    since = datetime.datetime.utcnow() - datetime.timedelta(hours=keep)
    bad_paths = [paths[i] for i, d, in enumerate(dates) if d < since]
    if len(bad_paths) > 0:
        click.echo("Found {} runs, {} are older than {} hours".format(len(paths), len(bad_paths), keep))
        click.confirm(click.style(
                "Are you sure you want to remove %i runs?" % len(bad_paths), bold=True), abort=True)
        for path in bad_paths:
            shutil.rmtree(path)
        click.echo(click.style("Success!", fg="green"))
    else:
        click.echo(click.style("No runs older than %i hours found" % keep, fg="red"))

@cli.command(context_settings=RUN_CONTEXT, name="docker-run")
@click.pass_context
@click.argument('docker_run_args', nargs=-1)
@click.option('--help')
def docker_run(ctx, docker_run_args, help):
    """Simple docker wrapper that adds WANDB_API_KEY and WANDB_DOCKER to any docker run command.
    This will also set the runtime to nvidia if the nvidia-docker executable is present on the system
    and --runtime wasn't set.
    """
    args = list(docker_run_args)
    if len(args) > 0 and args[0] == "run":
        args.pop(0)
    if help or len(args) == 0:
        wandb.termlog("This commands adds wandb env variables to your docker run calls")
        subprocess.call(['docker', 'run'] + args + ['--help'])
        exit()
    #TODO: is this what we want?
    if len([a for a in args if a.startswith("--runtime")]) == 0 and find_executable('nvidia-docker'):
        args = ["--runtime", "nvidia"] + args
    #TODO: image_from_docker_args uses heuristics to find the docker image arg, there are likely cases
    #where this won't work
    image = util.image_from_docker_args(args)
    resolved_image = None
    if image:
        resolved_image = wandb.docker.image_id(image)
    if resolved_image:
        args = ['-e', 'WANDB_DOCKER=%s' % resolved_image] + args
    else:
        wandb.termlog("Couldn't detect image argument, running command without the WANDB_DOCKER env variable")
    if api.api_key:
        args = ['-e', 'WANDB_API_KEY=%s' % api.api_key] + args
    else:
        wandb.termlog("Not logged in, run `wandb login` from the host machine to enable result logging")
    subprocess.call(['docker', 'run'] + args)


@cli.command(context_settings=RUN_CONTEXT)
@click.pass_context
@click.argument('docker_run_args', nargs=-1)
@click.argument('docker_image', required=False)
@click.option('--nvidia/--no-nvidia', default=find_executable('nvidia-docker') != None,
              help='Use the nvidia runtime, defaults to nvidia if nvidia-docker is present')
@click.option('--digest', is_flag=True, default=False, help="Output the image digest and exit")
@click.option('--jupyter/--no-jupyter', default=False, help="Run jupyter lab in the container")
@click.option('--dir', default="/app", help="Which directory to mount the code in the container")
@click.option('--no-dir', is_flag=True, help="Don't mount the current directory")
@click.option('--shell', default="/bin/bash", help="The shell to start the container with")
@click.option('--port', default="8888", help="The host port to bind jupyter on")
@click.option('--cmd', help="The command to run in the container")
@click.option('--no-tty', is_flag=True, default=False, help="Run the command without a tty")
@display_error
def docker(ctx, docker_run_args, docker_image, nvidia, digest, jupyter, dir, no_dir, shell, port, cmd, no_tty):
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
    if not find_executable('docker'):
        raise ClickException(
            "Docker not installed, install it from https://docker.com")
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
            "Couldn't find image locally or in a registry, try running `docker pull %s`" % image)
    if digest:
        sys.stdout.write(resolved_image)
        exit(0)

    existing = wandb.docker.shell(
        ["ps", "-f", "ancestor=%s" % resolved_image, "-q"])
    if existing:
        question = {
            'type': 'confirm',
            'name': 'attach',
            'message': "Found running container with the same image, do you want to attach?",
        }
        result = whaaaaat.prompt([question])
        if result and result['attach']:
            subprocess.call(['docker', 'attach', existing.split("\n")[0]])
            exit(0)
    cwd = os.getcwd()
    command = ['docker', 'run', '-e', 'LANG=C.UTF-8', '-e', 'WANDB_DOCKER=%s' % resolved_image, '--ipc=host',
                '-v', wandb.docker.entrypoint+':/wandb-entrypoint.sh', '--entrypoint', '/wandb-entrypoint.sh']
    if nvidia:
        command.extend(['--runtime', 'nvidia'])
    if not no_dir:
        #TODO: We should default to the working directory if defined
        command.extend(['-v', cwd+":"+dir, '-w', dir])
    if api.api_key:
        command.extend(['-e', 'WANDB_API_KEY=%s' % api.api_key])
    else:
        wandb.termlog("Couldn't find WANDB_API_KEY, run `wandb login` to enable streaming metrics")
    if jupyter:
        command.extend(['-e', 'WANDB_ENSURE_JUPYTER=1', '-p', port+':8888'])
        no_tty = True
        cmd = "jupyter lab --no-browser --ip=0.0.0.0 --allow-root --NotebookApp.token= --notebook-dir %s" % dir
    command.extend(args)
    if no_tty:
        command.extend([image, shell, "-c", cmd])
    else:
        if cmd:
            command.extend(['-e', 'WANDB_COMMAND=%s' % cmd])
        command.extend(['-it', image, shell])
        wandb.termlog("Launching docker container \U0001F6A2")
    subprocess.call(command)



MONKEY_CONTEXT = copy.copy(CONTEXT)
MONKEY_CONTEXT['allow_extra_args'] = True
MONKEY_CONTEXT['ignore_unknown_options'] = True

@cli.command(context_settings=MONKEY_CONTEXT, help="Run any script with wandb", hidden=True)
@click.pass_context
@click.argument('program')
@click.argument('args', nargs=-1)
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
        with open(program, 'rb') as fp:
            code = compile(fp.read(), program, 'exec')
    except IOError:
        click.echo(click.style("Could not launch program: %s" % program, fg="red"))
        sys.exit(1)
    globs = {
            '__file__': program,
            '__name__': '__main__',
            '__package__': None,
            'wandb_magic_install': magic_install,
        }
    prep = '''
import __main__
__main__.__file__ = "%s"
wandb_magic_install()
''' % program
    magic_run(prep, globs, None)
    magic_run(code, globs, None)


@cli.command(context_settings=CONTEXT, help="Create a sweep")
@click.pass_context
@click.option("--project", "-p", default=None, envvar=env.PROJECT, help="The project of the sweep.")
@click.option("--entity", "-e", default=None, envvar=env.ENTITY, help="The entity scope for the project.")
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

    if api.api_key is None:
        termlog("Login to W&B to use the sweep feature")
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
            'Updating' if sweep_obj_id else 'Creating',
            config_yaml))
    try:
        yaml_file = open(config_yaml)
    except (OSError, IOError):
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

    entity = entity or env.get_entity() or config.get('entity')
    project = project or env.get_project() or config.get('project') or util.auto_project_name(
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
    entity = entity or env.get_entity()
    project = project or env.get_project()

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
@click.option("--project", "-p", default=None, envvar=env.PROJECT, help="The project of the sweep.")
@click.option("--entity", "-e", default=None, envvar=env.ENTITY, help="The entity scope for the project.")
@click.option("--count", default=None, type=int, help="The max number of runs for this agent.")
@click.argument('sweep_id')
@display_error
def agent(ctx, project, entity, count, sweep_id):
    if api.api_key is None:
        termlog("Login to W&B to use the sweep agent feature")
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


if __name__ == "__main__":
    cli()
