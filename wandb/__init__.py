# -*- coding: utf-8 -*-

__author__ = """Chris Van Pelt"""
__email__ = 'vanpelt@wandb.com'
__version__ = '0.4.19'

import types, sys, logging, os

# We use the hidden version if it already exists, otherwise non-hidden.
if os.path.exists('.wandb'):
    __stage_dir__ = '.wandb/'
else:
    __stage_dir__ = "wandb/"

from .git_repo import GitRepo
from .api import Api, Error
from .sync import Sync
from .config import Config
from .results import Results
from .summary import Summary
from .history import History
from .keras import WandBKerasCallback

logging.basicConfig(
    filemode="w",
    filename=__stage_dir__+'debug.log',
    level=logging.DEBUG)

def push(*args, **kwargs):
    Api().push(*args, **kwargs)

def pull(*args, **kwargs):
    Api().pull(*args, **kwargs)

def sync(globs=['*'], **kwargs):
    api = Api()
    if api.api_key is None:
        raise Error("No API key found, run `wandb login` or set WANDB_API_KEY")
    #TODO: wandb describe
    sync = Sync(api, **kwargs)
    sync.watch(files=globs)
    return sync.run

__all__ = ["Api", "Error", "Config", "Results", "History", "Summary",
        "WandBKerasCallback"]
