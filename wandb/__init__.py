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


def _debugger(*args):
    import pdb
    pdb.set_trace()


# Will be set to the run object for the current run, as returned by
# wandb.init(). We may want to get rid of this, but WandbKerasCallback
# relies on it, and it improves the API a bit (user doesn't have to
# pass the run into WandbKerasCallback)
run = None


def init(job_type='train'):
    global run
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

    try:
        signal.signal(signal.SIGQUIT, _debugger)
    except AttributeError:
        pass

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

        if bool(os.environ.get('WANDB_SHOW_RUN')):
            webbrowser.open_new_tab(run.get_url(api))
    elif run.mode == 'dryrun':
        termlog('wandb dryrun mode. Use "wandb run <script>" to save results to wandb.')
        termlog()
    else:
        termlog('Invalid run mode "%s". Please unset WANDB_MODE to do a dry run or')
        termlog('run with "wandb run" to do a real run.')
        sys.exit(1)

    atexit.register(run.close_files)

    os.environ['WANDB_INITED'] = '1'

    return run


__all__ = ['init', 'termlog', 'run', 'types']
