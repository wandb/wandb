# -*- coding: utf-8 -*-

__author__ = """Chris Van Pelt"""
__email__ = 'vanpelt@wandb.com'
__version__ = '0.4.19'

import types
import sys
import logging
import os

# We use the hidden version if it already exists, otherwise non-hidden.
if os.path.exists('.wandb'):
    __stage_dir__ = '.wandb/'
elif os.path.exists('wandb'):
    __stage_dir__ = "wandb/"
else:
    __stage_dir__ = None

from .git_repo import GitRepo
from .api import Api, Error
from .sync import Sync
from .config import Config
from .results import Results
from .summary import Summary
from .history import History
from .keras import WandBKerasCallback
from wandb import wandb_run

# Three possible modes:
#     'cli': running from "wandb" command
#     'run': we're a script launched by "wandb run"
#     'dryrun': we're a script not launched by "wandb run"
MODE = os.environ.get('WANDB_MODE', 'dryrun')

# The current run (a Run object)
run = None

if MODE == 'run':
    run = wandb_run.Run(os.getenv('WANDB_RUN_ID'),
                        os.getenv('WANDB_RUN_DIR'),
                        Config())
elif MODE == 'dryrun':
    run_id = wandb_run.generate_id()
    run = wandb_run.Run(run_id, wandb_run.run_dir_path(
        run_id, dry=True), Config())


# called by cli.py
# Even when running the wandb cli, __init__.py is imported before main() runs, so we set
# cli mode afterward. This means there's a period of time before this call when MODE will
# be dryrun
def _set_cli_mode():
    global MODE, run
    MODE = 'cli'
    run = None


if __stage_dir__ is not None:
    log_fname = __stage_dir__ + 'debug.log'
else:
    log_fname = './wandb-debug.log'
logging.basicConfig(
    filemode="w",
    filename=log_fname,
    level=logging.DEBUG)


def push(*args, **kwargs):
    Api().push(*args, **kwargs)


def pull(*args, **kwargs):
    Api().pull(*args, **kwargs)


def sync(globs=['*'], **kwargs):
    print('wandb Deprecated')
    return
    global run
    if os.getenv('WANDB_CLI_LAUNCHED'):
        run = Run(os.getenv('WANDB_RUN_ID'), os.getenv('WANDB_RUN_DIR'), {})
        return
    api = Api()
    if api.api_key is None:
        raise Error("No API key found, run `wandb login` or set WANDB_API_KEY")
    # TODO: wandb describe
    sync = Sync(api, **kwargs)
    sync.watch(files=globs)
    run = sync.run
    return run


__all__ = ["Api", "Error", "Config", "Results", "History", "Summary",
           "WandBKerasCallback"]
