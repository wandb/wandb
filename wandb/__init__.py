# -*- coding: utf-8 -*-

__author__ = """Chris Van Pelt"""
__email__ = 'vanpelt@wandb.com'
__version__ = '0.4.46'

import atexit
import click
import logging
import os
import signal
import six
import socket
import sys
import traceback
import types
import webbrowser

from wandb import sparkline

# We use the hidden version if it already exists, otherwise non-hidden.
if os.path.exists('.wandb'):
    __stage_dir__ = '.wandb/'
elif os.path.exists('wandb'):
    __stage_dir__ = "wandb/"
else:
    __stage_dir__ = None

SCRIPT_PATH = os.path.abspath(sys.argv[0])


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

# Three possible modes:
#     'cli': running from "wandb" command
#     'run': we're a script launched by "wandb run"
#     'dryrun': we're a script not launched by "wandb run"


def termlog(string='', newline=True):
    if string:
        line = '%s: %s' % (click.style('wandb', fg='blue', bold=True), string)
    else:
        line = ''
    click.echo(line, file=sys.stderr, nl=newline)


# Will be set to the run object for the current run, as returned by
# wandb.init(). We may want to get rid of this, but WandbKerasCallback
# relies on it, and it improves the API a bit (user doesn't have to
# pass the run into WandbKerasCallback)
run = None
_exit_hooks = None


def init(job_type='train'):
    global run
    global _exit_hooks
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

    # The WANDB_DEBUG check ensures tests still work.
    if not wandb_dir() and not os.getenv('WANDB_DEBUG'):
        termlog('wandb.init() called but directory not initialized.\n'
              'Please run "wandb init" to get started')
        sys.exit(1)

    syncer = None

    run = wandb_run.Run.from_environment_or_defaults()
    run.job_type = job_type
    run.set_environment()
    if run.mode == 'run':
        assert run.storage_id
        run.config.set_run_dir(run.dir)  # set the run directory in the config so it actually gets persisted
        api = wandb_api.Api()
        api.set_current_run_id(run.id)
        # we have to write job_type here because we don't know it before init()
        api.upsert_run(id=run.storage_id, job_type=job_type)

        def config_persist_callback():
            api.upsert_run(id=run.storage_id, config=run.config.as_dict())
        run.config.set_persist_callback(config_persist_callback)

        _exit_hooks = ExitHooks()
        _exit_hooks.hook()

        if bool(os.environ.get('WANDB_SHOW_RUN')):
            webbrowser.open_new_tab(run.get_url(api))
    elif run.mode == 'dryrun':
        termlog('wandb dryrun mode. Use "wandb run <script>" to save results to wandb.')
        termlog()

        atexit.register(run.close_files)
    else:
        termlog('Invalid run mode "%s". Please unset WANDB_MODE to do a dry run or')
        termlog('run with "wandb run" to do a real run.')
        sys.exit(1)

    os.environ['WANDB_INITED'] = '1'

    return run


class ExitHooks(object):
    def __init__(self):
        self._signal = None
        self.exit_code = None
        self.exception = None

    def hook(self):
        signal.signal(signal.SIGTERM, self._sigkill)
        try:
            signal.signal(signal.SIGQUIT, self._debugger)
        except AttributeError:
            pass
        atexit.register(self.atexit)
        self._orig_exit = sys.exit
        self._orig_excepthook = sys.excepthook
        sys.exit = self.exit
        sys.excepthook = self.excepthook

    def _debugger(self, *args):
        import pdb
        pdb.set_trace()

    def atexit(self):
        termlog()
        if self._signal == signal.SIGTERM:
            termlog(
                'Script ended because of SIGTERM, press ctrl-c to abort syncing.')
        elif isinstance(self.exception, KeyboardInterrupt):
            termlog(
                'Script ended because of ctrl-c, press ctrl-c again to abort syncing.')
        elif self.exception:
            termlog(
                'Script ended because of Exception, press ctrl-c to abort syncing.')
        else:
            termlog('Script ended.')

        # Show run summary/history
        if run.has_summary:
            summary = run.summary.summary
            termlog('Run summary:')
            max_len = max([len(k) for k in summary.keys()])
            format_str = '  {:>%s} {}' % max_len
            for k, v in summary.items():
                termlog(format_str.format(k, v))
        if run.has_history:
            history_keys = run.history.keys()
            termlog('Run history:')
            max_len = max([len(k) for k in history_keys])
            for key in history_keys:
                vals = util.downsample(run.history.column(key), 40)
                line = sparkline.sparkify(vals)
                format_str = u'  {:>%s} {}' % max_len
                termlog(format_str.format(key, line))
        if run.has_examples:
            termlog('Saved %s examples' % run.examples.count())

        run.close_files()

    def _sigkill(self, *args):
        self._signal = signal.SIGTERM
        # Send keyboard interrupt to ourself! This triggers the python behavior of stopping the
        # running script and running the atexit handlers which don't normally get called
        # when the script is terminated by a signal.
        os.kill(os.getpid(), signal.SIGINT)

    def exit(self, code=0):
        self.exit_code = code
        self._orig_exit(code)

    def excepthook(self, exc_type, exc, *args):
        self.exception = exc
        self._orig_excepthook(exc_type, exc, *args)


__all__ = ['init', 'termlog', 'run', 'types']
