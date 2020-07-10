# -*- coding: utf-8 -*-
"""
module init
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

__version__ = '0.0.29'

import sys

from wandb.errors import Error

PY3 = sys.version_info.major == 3 and sys.version_info.minor >= 6
if PY3:
    TYPE_CHECKING = True
    from wandb import sdk as wandb_sdk
else:
    TYPE_CHECKING = False
    from wandb import sdk_py27 as wandb_sdk

init = wandb_sdk.init
setup = wandb_sdk.setup
save = wandb_sdk.save
watch = wandb_sdk.watch
login = wandb_sdk.login
Settings = wandb_sdk.Settings

from wandb.apis import InternalApi, PublicApi
from wandb.errors.error import CommError

from wandb.lib import preinit as _preinit
from wandb.lib import lazyloader as _lazyloader
from wandb.errors.term import termlog, termerror, termwarn
from wandb import wandb_torch
from wandb import util

# Move this (keras.__init__ expects it at top level)
from wandb.data_types import Graph
from wandb.data_types import Image
from wandb.data_types import Video
from wandb.data_types import Audio
from wandb.data_types import Table
from wandb.data_types import Html
from wandb.data_types import Object3D
from wandb.data_types import Molecule
from wandb.data_types import Histogram
from wandb.data_types import Graph

from wandb.wandb_agent import agent
from wandb.wandb_controller import sweep, controller

from wandb import superagent
#from wandb.core import *
from wandb.viz import visualize
from wandb import plots

# Used to make sure we don't use some code in the incorrect process context
_IS_INTERNAL_PROCESS = False

def _set_internal_process():
    global _IS_INTERNAL_PROCESS
    _IS_INTERNAL_PROCESS = True

def _is_internal_process():
    return _IS_INTERNAL_PROCESS

from wandb.lib.ipython import _get_python_type

# toplevel:
# save()
# restore()
# login()
# sweep()
# agent()

# globals
Api = PublicApi
run = None
config = _preinit.PreInitObject("wandb.config")
summary = _preinit.PreInitObject("wandb.summary")
log = _preinit.PreInitCallable("wandb.log")
join = _preinit.PreInitCallable("wandb.join")

keras = _lazyloader.LazyLoader('wandb.keras', globals(), 'wandb.framework.keras')
sklearn = _lazyloader.LazyLoader('wandb.sklearn', globals(), 'wandb.sklearn')

__all__ = [
    "__version__",
    "init",
    "setup",
    "save",
]
