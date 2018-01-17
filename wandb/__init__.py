# -*- coding: utf-8 -*-

__author__ = """Chris Van Pelt"""
__email__ = 'vanpelt@wandb.com'
__version__ = '0.4.43'

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
    # after a parent has (only the parent will sync files/stdout/stderr).
    # This doesn't protect against the case where the parent doesn't call
    # wandb.init but two children do.
    if run or os.getenv('WANDB_INITED'):
        return run

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

    config = wandb_config.Config(config_paths=conf_paths,
                                 wandb_dir=__stage_dir__, run_dir=run_dir)
    run = wandb_run.Run(run_id, run_dir, config)
    termlog()
    if mode == 'run':
        api = wandb_api.Api()
        if api.api_key is None:
            raise wandb_api.Error(
                "No API key found, run `wandb login` or set WANDB_API_KEY")
        api.set_current_run_id(run.id)

        syncer = sync.Sync(api, job_type, run, config=run.config, sweep_id=sweep_id)
        syncer.watch(files='*', show_run=show_run)

        root = api.git.root
        remote_url = api.git.remote_url
        host = socket.gethostname()
        # handle non-git directories
        if not root:
            root = os.path.abspath(os.getcwd())
            remote_url = 'file://%s%s' % (host, root)

        # Load description and write it to the run directory.
        dpath = run.description_path
        description = None
        if os.path.exists(dpath):
            with open(dpath) as f:
                description = f.read()
        # An empty description.md may have been created by sync.Sync() so it's
        # important that we disregard empty strings here.
        if not description:
            description = os.getenv('WANDB_DESCRIPTION')
        if not description:
            description = run.id
        with open(dpath, 'w') as f:
            f.write(description)

        entity = api.settings("entity")
        project = api.settings("project")
        program_path = os.path.relpath(SCRIPT_PATH, root)

        # TODO: better failure handling
        upsert_result = api.upsert_run(name=run.id, project=project, entity=entity,
                                             config=config.as_dict(), description=description, host=host,
                                             program_path=program_path, job_type=job_type, repo=remote_url,
                                             sweep_name=sweep_id)
        run_storage_id = upsert_result['id']

        def config_persist_callback():
            api.upsert_run(id=run_storage_id, config=config.as_dict())
        config._set_persist_callback(config_persist_callback)

        # we do this after starting sync.Sync() because this atexit handler needs
        # to happen before the one in sync.Sync.
        _exit_hooks = ExitHooks()
        _exit_hooks.hook()
    elif mode == 'dryrun':
        termlog(
            'wandb dryrun mode. Use "wandb run <script>" to save results to wandb.')
    termlog('Run directory: %s' % os.path.relpath(run.dir))
    termlog()
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
