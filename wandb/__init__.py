# -*- coding: utf-8 -*-

from __future__ import absolute_import, print_function

__author__ = """Chris Van Pelt"""
__email__ = 'vanpelt@wandb.com'
__version__ = '0.5.7'

import atexit
import click
import json
import logging
import time
import os
try:
    import pty
except ImportError:  # windows
    pty = None
import signal
import six
import socket
import subprocess
import sys
import traceback
try:
    import tty
except ImportError:  # windows
    tty = None
import types
import webbrowser

from . import io_wrap

# We use the hidden version if it already exists, otherwise non-hidden.
if os.path.exists('.wandb'):
    __stage_dir__ = '.wandb/'
elif os.path.exists('wandb'):
    __stage_dir__ = "wandb/"
else:
    __stage_dir__ = None

SCRIPT_PATH = os.path.abspath(sys.argv[0])
START_TIME = time.time()


def wandb_dir():
    return __stage_dir__


def _set_stage_dir(stage_dir):
    # Used when initing a new project with "wandb init"
    global __stage_dir__
    __stage_dir__ = stage_dir


if __stage_dir__ is not None:
    log_fname = __stage_dir__ + 'debug.log'
else:
    log_fname = './wandb-debug.log'
logging.basicConfig(
    filemode="w",
    filename=log_fname,
    level=logging.DEBUG)
logger = logging.getLogger(__name__)


class Error(Exception):
    """Base W&B Error"""
    # For python 2 support

    def encode(self, encoding):
        return self.message


# These imports need to be below __stage_dir__ declration until we remove
# 'from wandb import __stage_dir__' from api.py etc.
from wandb import wandb_types as types
from wandb import api as wandb_api
from wandb import config as wandb_config
from wandb import wandb_run
from wandb import wandb_socket
from wandb import util
from wandb.media import Image
# Three possible modes:
#     'cli': running from "wandb" command
#     'run': we're a script launched by "wandb run"
#     'dryrun': we're a script not launched by "wandb run"

LOG_STRING = click.style('wandb', fg='blue', bold=True)
ERROR_STRING = click.style('ERROR', bg='red', fg='green')


def termlog(string='', newline=True):
    if string:
        line = '\n'.join(['%s: %s' % (LOG_STRING, s)
                          for s in string.split('\n')])
    else:
        line = ''
    click.echo(line, file=sys.stderr, nl=newline)


def termerror(string):
    string = '\n'.join(['%s: %s' % (ERROR_STRING, s)
                        for s in string.split('\n')])
    termlog(string=string, newline=True)


def _debugger(*args):
    import pdb
    pdb.set_trace()


class Callbacks():
    @property
    def Keras(self):
        from .wandb_keras import WandbKerasCallback
        return WandbKerasCallback


callbacks = Callbacks()


class ExitHooks(object):
    def __init__(self):
        self.exit_code = 0
        self.exception = None

    def hook(self):
        self._orig_exit = sys.exit
        sys.exit = self.exit
        sys.excepthook = self.exc_handler

    def exit(self, code=0):
        self.exit_code = code
        self._orig_exit(code)

    def exc_handler(self, exc_type, exc, *tb):
        self.exit_code = 1
        self.exception = exc
        if issubclass(exc_type, Error):
            termerror(str(exc))
        if issubclass(exc_type, KeyboardInterrupt):
            self.exit_code = 255
            traceback.print_exception(exc_type, exc, *tb)
        else:
            traceback.print_exception(exc_type, exc, *tb)


def _init_headless(api, run, job_type, cloud=True):
    if 'WANDB_DESCRIPTION' in os.environ:
        run.description = os.environ['WANDB_DESCRIPTION']

    # TODO: better failure handling
    root = api.git.root
    remote_url = api.git.remote_url
    host = socket.gethostname()
    # handle non-git directories
    if not root:
        root = os.path.abspath(os.getcwd())
        remote_url = 'file://%s%s' % (host, root)

    try:
        import __main__
        program = __main__.__file__
    except (ImportError, AttributeError):
        # probably `python -c`, an embedded interpreter or something
        program = '<python with no main file>'

    # we need to create the run first of all so history and summary syncing
    # work even if the syncer process is slow to start.
    if cloud:
        upsert_result = api.upsert_run(name=run.id,
                                       project=api.settings("project"),
                                       entity=api.settings("entity"),
                                       config=run.config.as_dict(), description=run.description, host=host,
                                       program_path=program, repo=remote_url, sweep_name=run.sweep_id,
                                       job_type=job_type)
        run.storage_id = upsert_result['id']
    env = dict(os.environ)
    run.set_environment(env)

    server = wandb_socket.Server()
    run.socket = server
    hooks = ExitHooks()
    hooks.hook()

    stdout_master_fd, stdout_slave_fd = pty.openpty()
    stderr_master_fd, stderr_slave_fd = pty.openpty()

    # raw mode so carriage returns etc. don't get added by the terminal driver
    tty.setraw(stdout_master_fd)
    tty.setraw(stderr_master_fd)

    headless_args = {
        'command': 'headless',
        'pid': os.getpid(),
        'stdout_master_fd': stdout_master_fd,
        'stderr_master_fd': stderr_master_fd,
        'cloud': cloud,
        'job_type': job_type,
        'program': program,
        'port': server.port
    }
    internal_cli_path = os.path.join(
        os.path.dirname(__file__), 'internal_cli.py')

    if six.PY2:
        # TODO(adrian): close_fds=False is bad for security. we set
        # it so we can pass the PTY FDs to the wandb process. We
        # should use subprocess32, which has pass_fds.
        popen_kwargs = {'close_fds': False}
    else:
        popen_kwargs = {'pass_fds': [stdout_master_fd, stderr_master_fd]}

    # TODO(adrian): make wandb the foreground process so we don't give
    # up terminal control until syncing is finished.
    # https://stackoverflow.com/questions/30476971/is-the-child-process-in-foreground-or-background-on-fork-in-c
    subprocess.Popen(['/usr/bin/env', 'python', internal_cli_path, json.dumps(
        headless_args)], env=env, **popen_kwargs)
    os.close(stdout_master_fd)
    os.close(stderr_master_fd)

    stdout_slave = os.fdopen(stdout_slave_fd, 'wb')
    stderr_slave = os.fdopen(stderr_slave_fd, 'wb')

    stdout_redirector = io_wrap.FileRedirector(sys.stdout, stdout_slave)
    stderr_redirector = io_wrap.FileRedirector(sys.stderr, stderr_slave)

    stdout_redirector.redirect()
    if os.environ.get('WANDB_DEBUG') != 'true':
        stderr_redirector.redirect()

    # Listen on the socket waiting for the wandb process to be ready
    server.listen(5)

    def done():
        server.done(hooks.exit_code)
        logger.info("Waiting for wandb process to finish")
        server.listen()

    atexit.register(done)



# Will be set to the run object for the current run, as returned by
# wandb.init(). We may want to get rid of this, but WandbKerasCallback
# relies on it, and it improves the API a bit (user doesn't have to
# pass the run into WandbKerasCallback)
run = None


def init(job_type='train', config=None):
    global run
    global __stage_dir__
    # If a thread calls wandb.init() it will get the same Run object as
    # the parent. If a child process with distinct memory space calls
    # wandb.init(), it won't get an error, but it will get a result of
    # None.
    # This check ensures that a child process can safely call wandb.init()
    # after a parent has (only the parent will create the Run object).
    # This doesn't protect against the case where the parent doesn't call
    # wandb.init but two children do.
    if run or os.getenv('WANDB_INITED'):
        return run

    if not wandb_dir():
        __stage_dir__ = "wandb"
        util.mkdir_exists_ok(__stage_dir__)

    try:
        signal.signal(signal.SIGQUIT, _debugger)
    except AttributeError:
        pass

    run = wandb_run.Run.from_environment_or_defaults()
    run.job_type = job_type
    run.set_environment()
    if config:
        run.config.update(config)
    api = wandb_api.Api()
    api.set_current_run_id(run.id)
    if run.mode == 'run':
        api.ensure_configured()
        if run.storage_id:
            # we have to write job_type here because we don't know it before init()
            api.upsert_run(id=run.storage_id, job_type=job_type)
        else:
            _init_headless(api, run, job_type)

        def config_persist_callback():
            api.upsert_run(id=run.storage_id, config=run.config.as_dict())
        # set the run directory in the config so it actually gets persisted
        run.config.set_run_dir(run.dir)
        run.config.set_persist_callback(config_persist_callback)

        if bool(os.environ.get('WANDB_SHOW_RUN')):
            webbrowser.open_new_tab(run.get_url(api))
    elif run.mode == 'dryrun':
        termlog(
            'wandb dry run mode. Run `wandb board` from this directory to see results')
        termlog()
        run.config.set_run_dir(run.dir)
        _init_headless(api, run, job_type, False)
    else:
        termlog(
            'Invalid run mode "%s". Please unset WANDB_MODE to do a dry run or' % run.mode)
        termlog('run with "wandb run" to do a real run.')
        sys.exit(1)

    atexit.register(run.close_files)

    os.environ['WANDB_INITED'] = '1'

    return run


__all__ = ['init', 'termlog', 'run', 'types', 'callbacks']
