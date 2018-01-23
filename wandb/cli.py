# -*- coding: utf-8 -*-
from __future__ import print_function

import click
import sys
import copy
import random
import time
import os
import re
import netrc
import logging
import json
import glob
import io
import signal
import stat
import subprocess
from functools import wraps
from click.utils import LazyFile
from click.exceptions import BadParameter, ClickException
import click_log
import whaaaaat
import sys
import traceback
import textwrap
import requests
import yaml

import wandb
from wandb.api import Api
from wandb.config import Config
from wandb.pusher import LogPuller
from wandb import agent as wandb_agent
from wandb import wandb_run
from wandb import wandb_dir
from wandb import util

DOCS_URL = 'http://docs.wandb.com/'

logger = logging.getLogger(__name__)


class ClickWandbException(ClickException):
    def format_message(self):
        log_file = util.get_log_file_path()
        orig_type = '%s.%s' % (self.orig_type.__module__,
                               self.orig_type.__name__)
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

    if len(result) == 0:
        project = click.prompt("Enter a name for your first project")
        description = editor()
        api.upsert_project(project, entity=entity, description=description)
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
            project = click.prompt("Enter a name for your new project")
            description = editor()
            api.upsert_project(project, entity=entity, description=description)
        else:
            ids = [res['id'] for res in result if res['name'] == project]
            if len(ids) > 0:
                api.upsert_project(project, id=ids[0], entity=entity)

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
    root_logger = logging.getLogger()
    click_log.basic_config(root_logger)
    root_logger.setLevel(logging.WARN)


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
                 str(project['description']).split("\n")[0])
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

    # project, run = api.parse_slug(run, project=project)
    # existing = set()  # TODO: populate this set with the current files in the run dir
    # remote = api.download_urls(project, run)
    # not_synced = set()
    # remote_names = set([name for name in remote])
    # for file in existing:
    #    meta = remote.get(file)
    #    if meta and not api.file_current(file, meta['md5']):
    #        not_synced.add(file)
    #    elif not meta:
    #        not_synced.add(file)
    # TODO: remove items that exists and have the md5
    # only_remote = remote_names.difference(existing)
    # up_to_date = existing.difference(only_remote).difference(not_synced)
    # click.echo('File status for ' + click.style('"%s/%s" ' %
    #                                            (project, run), bold=True))
    # if len(not_synced) > 0:
    #    click.echo(click.style('Push needed: ', bold=True) +
    #               click.style(", ".join(not_synced), fg="red"))
    # if len(only_remote) > 0:
    #    click.echo(click.style('Pull needed: ', bold=True) +
    #               click.style(", ".join(only_remote), fg="red"))
    # if len(up_to_date) > 0:
    #    click.echo(click.style('Up to date: ', bold=True) +
    #               click.style(", ".join(up_to_date), fg="green"))


#@cli.command(context_settings=CONTEXT, help="Store notes for a future training run")
@display_error
def describe():
    path = wandb.__stage_dir__ + 'description.md'
    existing = (os.path.exists(path) and open(path).read()) or ''
    description = editor(existing)
    if description:
        with open(path, 'w') as file:
            file.write(description)
    click.echo(
        "Notes stored for next training run\nCalling wandb.sync() in your training script will persist them.")


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


#@cli.command(context_settings=CONTEXT, help="Push files to Weights & Biases")
@click.argument("run", envvar='WANDB_RUN')
@click.option("--project", "-p", envvar='WANDB_PROJECT', help="The project you wish to upload to.")
@click.option("--description", "-m", help="A description to associate with this upload.")
@click.option("--entity", "-e", default="models", envvar='WANDB_ENTITY', help="The entity to scope the listing to.")
@click.option("--force/--no-force", "-f", default=False, help="Whether to force git tag creation.")
@click.argument("files", type=click.File('rb'), nargs=-1)
@click.pass_context
@display_error
def push(ctx, run, project, description, entity, force, files):
    # TODO: do we support the case of a run with the same name as a file?
    if os.path.exists(run):
        raise BadParameter("Run id is required if files are specified.")
    project, run = api.parse_slug(run, project=project)

    click.echo("Updating run: {project}/{run}".format(
        project=click.style(project, bold=True), run=run))

    candidates = []
    if len(files) == 0:
        raise BadParameter("No files specified")

    # TODO: Deal with files in a sub directory
    api.push(project, files=[f.name for f in files], run=run,
             description=description, entity=entity, force=force, progress=sys.stdout)


#@cli.command(context_settings=CONTEXT, help="Pull files from Weights & Biases")
@click.argument("run", envvar='WANDB_RUN')
@click.option("--project", "-p", envvar='WANDB_PROJECT', help="The project you want to download.")
@click.option("--kind", "-k", default="all", type=click.Choice(['all', 'model', 'weights', 'other']))
@click.option("--entity", "-e", default="models", envvar='WANDB_ENTITY', help="The entity to scope the listing to.")
@display_error
def pull(project, run, kind, entity):
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
    url = api.app_url + '/profile'
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


def pending_loop(pod_id):
    def elip(times):
        return "." * (times % 4)
    i = 0
    wandb.termlog("Waiting for run to start%s\r" % elip(i), False)
    while True:
        try:
            i += 1
            if i > 3600:
                wandb.termlog("Unknown error")
                break
            res = requests.get(
                "http://kubed.endpoints.playground-111.cloud.goog/pods/%s" % pod_id)
            logging.debug('\n'.join([', '.join([c["type"], c["status"], str(c["message"])])
                                     for c in res.json()["status"]["conditions"]]))
            if res.json()["status"]["phase"] == "Pending":
                i -= 1
                for x in range(10):
                    i += 1
                    wandb.termlog("Waiting for run to start%s   \r" %
                                  elip(i), False)
                    time.sleep(1)
            else:
                wandb.termlog("Waiting no more.  Here we go!      ")
                break
        except:
            logging.debug(sys.exc_info()[1])
            time.sleep(10)


@cli.command(context_settings=RUN_CONTEXT, help="Log a job")
@click.argument('run_id')
def logs(run_id):
    puller = LogPuller(run_id)
    try:
        def signal_handler(signal, frame):
            print(
                "\n\nDetaching from remote instance, type `wandb logs %s` to resume logging" % run_id)
            exit(0)
        signal.signal(signal.SIGINT, signal_handler)
    except AttributeError:
        pass
    # run_id => pod_id
    # res = requests.get(
    #    "http://kubed.endpoints.playground-111.cloud.goog/pods/%s" % pod_id)
    # print([(c["type"], c["status"], c["message"])
    #       for c in res.json()["status"]["conditions"]])
    wandb.termlog("Connecting to logstream of %s\n" % run_id)
    puller.sync()


@cli.command(context_settings=RUN_CONTEXT, help="Launch a job")
@click.pass_context
@require_init
@click.argument('program')
@click.argument('args', nargs=-1)
@click.option('--id', default=None,
              help='Run id to use, default is to generate.')
@click.option('--dir', default=None,
              help='Files in this directory will be saved to wandb, defaults to wandb/run-<run_id>')
@click.option('--configs', default=None,
              help='Config file paths to load')
@click.option('--message', '-m', default=None,
              help='Message to associate with the run.')
@click.option("--show/--no-show", default=False,
              help="Open the run page in your default browser.")
@display_error
def run(ctx, program, args, id, dir, configs, message, show):
    env = copy.copy(os.environ)
    env['WANDB_MODE'] = 'run'
    if id is None:
        id = wandb_run.generate_id()
    env['WANDB_RUN_ID'] = id
    if dir is None:
        dir = wandb_run.run_dir_path(id, dry=False)
        util.mkdir_exists_ok(dir)
    if message:
        open(os.path.join(dir, 'description.md'), 'w').write('%s\n' % message)
    env['WANDB_RUN_DIR'] = dir
    if configs:
        env['WANDB_CONFIG_PATHS'] = configs
    if show:
        env['WANDB_SHOW_RUN'] = '1'
    command = [program] + list(args)

    try:
        signal.signal(signal.SIGQUIT, signal.SIG_IGN)
    except AttributeError:
        pass
    runner = util.find_runner(program)
    if runner:
        command = runner.split() + command
    proc = util.SafeSubprocess(command, env=env, read_output=False)
    try:
        proc.run()
    except (OSError, IOError):
        raise ClickException('Could not find program: %s' % command[0])
    # ignore SIGINT (ctrl-c), the child process will handle, and we'll
    # exit when the child process does.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    while True:
        time.sleep(0.1)
        exitcode = proc.poll()
        if exitcode is not None:
            wandb.termlog('job (%s) Process exited with code: %s' %
                          (program, exitcode))
            break


@cli.command(context_settings=CONTEXT, help="Create a sweep")
@click.pass_context
@require_init
@click.argument('config_yaml')
@display_error
def sweep(ctx, config_yaml):
    click.echo('Creating sweep from: %s' % config_yaml)
    config = yaml.load(open(config_yaml))
    sweep_id = api.upsert_sweep(config)
    print('Create sweep with ID:', sweep_id)


@cli.command(context_settings=CONTEXT, help="Run the wandb agent")
@click.argument('sweep_id')
@require_init
@display_error
def agent(sweep_id):
    click.echo('Starting wandb agent 🕵️')
    agent_api = wandb_agent.run_agent(sweep_id)

    # you can send local commands like so:
    # agent_api.command({'type': 'run', 'program': 'train.py',
    #                'args': ['--max_epochs=10']})
    while True:
        time.sleep(1)

#@cli.group()
#@click.pass_context
#@display_error
# def config(ctx):
#    """Manage this projects configuration.
#
# Examples:
#
#    wandb config set param=2 --description="Some tunning parameter"
#    wandb config del param
#    wandb config show
#    """
#    pass


#@config.command("init", help="Initialize a directory with wandb configuration")
#@display_error
# def config_init(prompt=True):
#    from wandb import get_stage_dir
#    config_path = os.path.join(os.getcwd(), get_stage_dir())
#    config = Config()
#    if os.path.isdir(config_path):
#        if prompt:
#            click.confirm(click.style("This directory is already initialized, should we overwrite it?", fg="red"), abort=True)
#    else:
#        os.mkdir(config_path)
#    config.epochs_desc = "Number epochs to train over"
#    config.epochs = 32
#    config.persist()
#    if prompt:
#        click.echo("""Configuration initialized, use `wandb config set` to set parameters.  Then in your training script:
# import wandb
# conf = wandb.sync()
# conf.batch_size
#""")


#@config.command(help="Show the current config")
#@click.option("--format", help="The format to dump the config as", default="python", type=click.Choice(['python', 'yaml', 'json']))
#@display_error
# def show(format, changed=[], diff=False):
#    if len(changed) == 0 and diff:
#        click.secho("No parameters were changed", fg="red")
#    elif diff:
#        click.echo("%i parameters changed: " % len(changed))
#    config = Config()
#    if len(vars(config)) == 0:
#        click.secho(
#            "No configuration found in this directory, run `wandb config init`", fg="red")
#    if format == "yaml":
#        click.echo("%s" % config)
#    elif format == "json":
#        click.echo(json.dumps(vars(config)))
#    elif format == "python":
#        res = ""
#        for key in set(config.keys + changed):
#            if config.desc(key):
#                res += "# %s\n" % config.desc(key)
#            style = None
#            if key in changed:
#                style = "green" if config.get(key) else "red"
#            res += click.style("%s=%r\n" % (key, config.get(key)),
#                               bold=True if style is None else False, fg=style)
#        click.echo(res)


#@config.command("import", help="Import configuration parameters")
#@click.option("--format", "-f", help="The format to parse the imported params", default="python", type=click.Choice(["python"]))
#@click.pass_context
#@display_error
# def import_config(ctx, format):
#    data = editor("# Paste python comments and variable definitions above")
#    desc = None
#    config = Config()
#    imported = []
#    if data:
#        for line in data.split("\n"):
#            if line.strip().startswith("#"):
#                desc = line.strip(" #")
#            elif "=" in line:
#                try:
#                    key, value = [str(part.strip())
#                                  for part in line.split("=")]
#                    if len(value) == 0:
#                        continue
#                    config[key] = value
#                    imported.append(key)
#                    if desc:
#                        config[key + "_desc"] = desc
#                    desc = None
#                except ValueError:
#                    logging.error("Invalid line: %s" % line)
#            else:
#                logging.warn("Skipping line %s", line)
#        config.persist()
#    ctx.invoke(show, changed=imported, diff=True)


#@config.command("set", help="Set config variables with key=value pairs")
#@click.argument("key_values", nargs=-1)
#@click.option("--description", "-d", help="A description for the config value if specifying one pair")
#@click.pass_context
#@display_error
# def config_set(ctx, key_values, description=None):
#    config = Config()
#    if len(key_values) == 0:
#        raise ClickException(
#            "Must specify at least 1 key value pair i.e. `wandb config set epochs=11`")
#    if len(key_values) > 1 and description:
#        raise ClickException(
#            "Description can only be specified with 1 key value pair.")
#    changed = []
#    for pair in key_values:
#        try:
#            key, value = pair.split("=")
#        except ValueError:
#            key = pair
#            value = None
#        if value:
#            changed.append(key)
#            config[str(key)] = value
#        if description:
#            config[str(key) + "_desc"] = description
#    config.persist()
#    ctx.invoke(show, changed=changed, diff=True)


#@config.command("del", help="Delete config variables")
#@click.argument("keys", nargs=-1)
#@click.pass_context
#@display_error
# def delete(ctx, keys):
#    config = Config()
#    if len(keys) == 0:
#        raise ClickException(
#            "Must specify at least 1 key i.e. `wandb config rm epochs`")
#    changed = []
#    for key in keys:
#        del config[str(key)]
#        changed.append(key)
#    config.persist()
#    ctx.invoke(show, changed=changed, diff=True)


if __name__ == "__main__":
    cli()
