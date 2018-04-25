# -*- coding: utf-8 -*-

from __future__ import absolute_import, print_function

__author__ = """Chris Van Pelt"""
__email__ = 'vanpelt@wandb.com'
__version__ = '0.5.16'

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

from . import env
from . import io_wrap

__root_dir__ = env.get_dir('./')

# We use the hidden version if it already exists, otherwise non-hidden.
if os.path.exists(os.path.join(__root_dir__, '.wandb')):
    __stage_dir__ = '.wandb/'
elif os.path.exists(os.path.join(__root_dir__, 'wandb')):
    __stage_dir__ = "wandb/"
else:
    __stage_dir__ = None

SCRIPT_PATH = os.path.abspath(sys.argv[0])
START_TIME = time.time()


def wandb_dir():
    return os.path.join(__root_dir__, __stage_dir__ or "wandb/")


def _set_stage_dir(stage_dir):
    # Used when initing a new project with "wandb init"
    global __stage_dir__
    __stage_dir__ = stage_dir


class Error(Exception):
    """Base W&B Error"""
    # For python 2 support

    def encode(self, encoding):
        return self.message


# These imports need to be below __stage_dir__ declration until we remove
# 'from wandb import __stage_dir__' from api.py etc.
import wandb.api
from wandb import wandb_types as types
from wandb import wandb_config
from wandb import wandb_run
from wandb import wandb_socket
from wandb import util
from wandb.media import Image
# Three possible modes:
#     'cli': running from "wandb" command
#     'run': we're a script launched by "wandb run"
#     'dryrun': we're a script not launched by "wandb run"


logger = logging.getLogger(__name__)
if __stage_dir__ is not None:
    log_fname = wandb_dir() + 'debug.log'
else:
    log_fname = './wandb-debug.log'


LOG_STRING = click.style('wandb', fg='blue', bold=True)
ERROR_STRING = click.style('ERROR', bg='red', fg='green')


# TODO(adrian): if output has been redirected, make this write to the original STDERR
# so it doesn't get logged to the backend
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
        termlog("DEPRECATED: wandb.callbacks is deprecated, use `from wandb.keras import WandbCallback`")
        from wandb.keras import WandbCallback
        return WandbCallback


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

    def was_ctrl_c(self):
        return isinstance(self.exception, KeyboardInterrupt)

    def exc_handler(self, exc_type, exc, *tb):
        self.exit_code = 1
        self.exception = exc
        if issubclass(exc_type, Error):
            termerror(str(exc))

        if self.was_ctrl_c():
            self.exit_code = 255

        traceback.print_exception(exc_type, exc, *tb)


def _init_headless(run, job_type, cloud=True):
    run.description = env.get_description(run.description)

    environ = dict(os.environ)
    run.set_environment(environ)

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
    wandb_process = subprocess.Popen(['/usr/bin/env', 'python', internal_cli_path, json.dumps(
        headless_args)], env=environ, **popen_kwargs)
    termlog('Started W&B process with PID {}'.format(wandb_process.pid))
    os.close(stdout_master_fd)
    os.close(stderr_master_fd)

    # Listen on the socket waiting for the wandb process to be ready
    try:
        success, message = server.listen(30)
    except KeyboardInterrupt:
        success = False
    else:
        if not success:
            termerror('W&B process (PID {}) did not respond'.format(wandb_process.pid))

    if not success:
        wandb_process.kill()
        for i in range(20):
            time.sleep(0.1)
            if wandb_process.poll() is not None:
                break
        if wandb_process.poll() is None:
            termerror('Failed to kill wandb process, PID {}'.format(wandb_process.pid))
        sys.exit(1)

    run.storage_id = message['storage_id']
    stdout_slave = os.fdopen(stdout_slave_fd, 'wb')
    stderr_slave = os.fdopen(stderr_slave_fd, 'wb')

    stdout_redirector = io_wrap.FileRedirector(sys.stdout, stdout_slave)
    stderr_redirector = io_wrap.FileRedirector(sys.stderr, stderr_slave)

    atexit.register(_user_process_finished, server, hooks, wandb_process, stdout_redirector, stderr_redirector)

    # redirect output last of all so we don't miss out on error messages
    stdout_redirector.redirect()
    if not env.get_debug():
        stderr_redirector.redirect()


def _user_process_finished(server, hooks, wandb_process, stdout_redirector, stderr_redirector):
    termlog("Waiting for wandb process to finish, PID {}".format(wandb_process.pid))
    server.done(hooks.exit_code)
    stdout_redirector.restore()
    stderr_redirector.restore()
    try:
        while wandb_process.poll() is None:
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass

    if wandb_process.poll() is None:
        termlog('Killing wandb process, PID {}'.format(wandb_process.pid))
        wandb_process.kill()


# Will be set to the run object for the current run, as returned by
# wandb.init(). We may want to get rid of this, but WandbCallback
# relies on it, and it improves the API a bit (user doesn't have to
# pass the run into WandbCallback)
run = None
config = None  # config object shared with the global run


def log(history_row):
    """Log a dict to the global run's history.

    Eg.

    wandb.log({'train-loss': 0.5, 'accuracy': 0.9})
    """
    run.history.add(history_row)


def ensure_configured():
    api = wandb.api.Api()
    # The WANDB_DEBUG check ensures tests still work.
    if not env.is_debug() and not api.settings('project'):
        termlog('wandb.init() called but system not configured.\n'
                      'Run "wandb init" or set environment variables to get started')
        sys.exit(1)


def uninit():
    """Undo the effects of init(). Useful for testing.
    """
    global run, config
    run = config = None


def try_to_set_up_logging():
    logger.setLevel(logging.DEBUG)
    try:
        handler = logging.FileHandler(log_fname, mode='w')
    except IOError as e:  # eg. in case wandb directory isn't writable
        if env.is_debug():
            raise
        else:
            termerror('Failed to set up logging: {}'.format(e))
            return False

    handler.setLevel(logging.DEBUG)
    logger.addHandler(handler)

    return True


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

    if __stage_dir__ is None:
        __stage_dir__ = "wandb"
        util.mkdir_exists_ok(wandb_dir())

    if not try_to_set_up_logging():
        sys.exit(1)

    try:
        signal.signal(signal.SIGQUIT, _debugger)
    except AttributeError:
        pass

    try:
        run = wandb_run.Run.from_environment_or_defaults()
    except IOError as e:
        termerror('Failed to create run directory: {}'.format(e))
        sys.exit(1)

    run.job_type = job_type
    run.set_environment()
    def set_global_config(c):
        global config  # because we already have a local config
        config = c
    set_global_config(run.config)

    if run.mode == 'clirun' or run.mode == 'run':
        ensure_configured()

        if run.mode == 'run':
            _init_headless(run, job_type)

        # set the run directory in the config so it actually gets persisted
        run.config.set_run_dir(run.dir)
    elif run.mode == 'dryrun':
        termlog(
            'wandb dry run mode. Run `wandb board` from this directory to see results')
        termlog()
        run.config.set_run_dir(run.dir)
        _init_headless(run, job_type, False)
    else:
        termlog(
            'Invalid run mode "%s". Please unset WANDB_MODE to do a dry run or' % run.mode)
        termlog('run with "wandb run" to do a real run.')
        sys.exit(1)

    if config:
        run.config.update(config)

    atexit.register(run.close_files)

    os.environ['WANDB_INITED'] = '1'

    return run


__all__ = ['init', 'config', 'termlog', 'run', 'types', 'callbacks']
