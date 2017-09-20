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
from .run import Run

# The current run (a Run object)
run = None
if os.getenv('WANDB_CLI_LAUNCHED'):
    run = Run(os.getenv('WANDB_RUN_ID'),
              os.getenv('WANDB_RUN_DIR'),
              Config())
else:
    try:
        os.mkdir(os.path.join(os.getcwd(), 'wandb-tmp'))
    except OSError:
        pass
    run = Run('tmp', 'wandb-tmp', Config())

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
