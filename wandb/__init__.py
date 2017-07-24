# -*- coding: utf-8 -*-

__author__ = """Chris Van Pelt"""
__email__ = 'vanpelt@wandb.com'
__version__ = '0.4.14'

import types, sys
from .git_repo import GitRepo
from .api import Api, Error
from .sync import Sync
from .config import Config
from .results import Results

def push(*args, **kwargs):
    Api().push(*args, **kwargs)

def pull(*args, **kwargs):
    Api().pull(*args, **kwargs)

def sync(name=None, **kwargs):
    api = Api()
    if api.api_key is None:
        raise Error("No API key found, run `wandb login` or set WANDB_API_KEY")
    project, bucket = api.parse_slug(name)
    #TODO: wandb describe
    sync = Sync(api, project=project, bucket=bucket, description=kwargs.get('description'))
    sync.watch(files=kwargs.get("files", []))

__all__ = ["Api", "Error", "Config", "Results"]