# -*- coding: utf-8 -*-

__author__ = """Chris Van Pelt"""
__email__ = 'vanpelt@wandb.com'
__version__ = '0.4.46'

import click
import types
import six
import sys
import logging
import os
import traceback

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
from wandb import sync
from wandb import wandb_run

# Three possible modes:
#     'cli': running from "wandb" command
#     'run': we're a script launched by "wandb run"
#     'dryrun': we're a script not launched by "wandb run"


_orig_stderr = sys.stderr


def termlog(string='', newline=True):
    if string:
        line = '%s: %s' % (click.style('wandb', fg='blue', bold=True), string)
    else:
        line = ''
    click.echo(line, file=_orig_stderr, nl=newline)


def _do_sync(mode, job_type, run, show_run, sweep_id=None):
    syncer = None
    termlog()
    if mode == 'run':
        api = wandb_api.Api()
        if api.api_key is None:
            raise wandb_api.Error(
                "No API key found, run `wandb login` or set WANDB_API_KEY")
        api.set_current_run_id(run.id)
        syncer = sync.Sync(api, job_type, run,
                           config=run.config, sweep_id=sweep_id)
        syncer.watch(files='*', show_run=show_run)
    elif mode == 'dryrun':
        termlog(
            'wandb dryrun mode. Use "wandb run <script>" to save results to wandb.')
    termlog('Run directory: %s' % os.path.relpath(run.dir))
    termlog()
    return syncer


# Will be set to the run object for the current run, as returned by
# wandb.init(). We may want to get rid of this, but WandbKerasCallback
# relies on it, and it improves the API a bit (user doesn't have to
# pass the run into WandbKerasCallback)
run = None


def init(job_type='train'):
    # The WANDB_DEBUG check ensures tests still work.
    if not __stage_dir__ and not os.getenv('WANDB_DEBUG'):
        print('wandb.init() called but directory not initialized.\n'
              'Please run "wandb init" to get started')
        sys.exit(1)

    # urllib3 logs all requests by default, which is ok as long as it's
    # going to wandb's debug.log, but it's a problem if the user's script
    # directs all logging to stdout/stderr (because all those requests will
    # get logged to wandb db, via making http requests). So we disable
    # request logging here. Scripts based on OpenAI's rllab have this
    # problem, maybe because of its use of Theano which uses the logging
    # module.
    # This is not an ideal solution. Other solutions:
    #    - Don't hook into to logging in user scripts, do it outside with
    #      "wandb run".
    #    - If the user's script sends logging to stdout, take back over and
    #      send it to wandb's debug.log. Not ideal.
    logging.getLogger('requests').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)

    # parse environment variables
    mode = os.getenv('WANDB_MODE', 'dryrun')
    run_id = os.getenv('WANDB_RUN_ID')
    if run_id is None:
        run_id = wandb_run.generate_id()
        os.environ['WANDB_RUN_ID'] = run_id
    run_dir = os.getenv('WANDB_RUN_DIR')
    if run_dir is None:
        run_dir = wandb_run.run_dir_path(run_id, dry=mode == 'dryrun')
        os.environ['WANDB_RUN_DIR'] = run_dir
    conf_paths = os.getenv('WANDB_CONFIG_PATHS', '')
    if conf_paths:
        conf_paths = conf_paths.split(',')
    show_run = bool(os.getenv('WANDB_SHOW_RUN'))
    sweep_id = os.getenv('WANDB_SWEEP_ID', None)

    config = None
    syncer = None

    def persist_config_callback():
        if syncer:
            syncer.update_config(config)
    config = wandb_config.Config(config_paths=conf_paths,
                                 wandb_dir=__stage_dir__, run_dir=run_dir,
                                 persist_callback=persist_config_callback)
    global run
    run = wandb_run.Run(run_id, run_dir, config)
    # This check ensures that a child process can safely call wandb.init()
    # after a parent has (only the parent will sync files/stdout/stderr).
    # This doesn't protect against the case where the parent doesn't call
    # wandb.init but two children do.
    if not os.getenv('WANDB_INITED'):
        syncer = _do_sync(mode, job_type, run, show_run, sweep_id=sweep_id)
        os.environ['WANDB_INITED'] = '1'
    return run


__all__ = ['init', 'termlog', 'run', 'types']
