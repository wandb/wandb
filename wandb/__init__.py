# -*- coding: utf-8 -*-

__author__ = """Chris Van Pelt"""
__email__ = 'vanpelt@wandb.com'
__version__ = '0.4.16'

import types, sys, logging, os
from .git_repo import GitRepo
from .api import Api, Error
from .sync import Sync
from .config import Config
from .results import Results

#TODO: check directory?
if os.path.exists(".wandb/"):
    logging.basicConfig(
        filemode="w",
        filename='.wandb/debug.log',
        level=logging.DEBUG)

def push(*args, **kwargs):
    Api().push(*args, **kwargs)

def pull(*args, **kwargs):
    Api().pull(*args, **kwargs)

def sync(globs=[], **kwargs):
    api = Api()
    if api.api_key is None:
        raise Error("No API key found, run `wandb login` or set WANDB_API_KEY")
    #TODO: wandb describe
    sync = Sync(api, **kwargs)
    sync.watch(files=globs)
    return sync.config

__all__ = ["Api", "Error", "Config", "Results"]