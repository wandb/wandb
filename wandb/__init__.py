# -*- coding: utf-8 -*-
"""
Wandb is a library to help track machine learning experiments.

For more information on wandb see https://docs.wandb.com.

The most commonly used functions/objects are:
- wandb.init — initialize a new run at the top of your training script
- wandb.config — track hyperparameters
- wandb.log — log metrics over time within your training loop
- wandb.save — save files in association with your run, like model weights
- wandb.restore — restore the state of your code when you ran a given run

For examples usage, see https://docs.wandb.com/library/example-projects
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

__version__ = '0.0.42'

# Used with pypi checks and other messages related to pip
_wandb_module = 'wandb-ng'

import sys

from wandb.errors import Error

# This needs to be early as other modules call it.
from wandb.errors.term import termlog, termerror, termwarn

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
helper = wandb_sdk.helper
Artifact = wandb_sdk.Artifact
Settings = wandb_sdk.Settings
Config = wandb_sdk.Config

from wandb.apis import InternalApi, PublicApi
from wandb.errors.error import CommError

from wandb.lib import preinit as _preinit
from wandb.lib import lazyloader as _lazyloader
from wandb import wandb_torch
from wandb import util

# Move this (keras.__init__ expects it at top level)
from wandb.data_types import Graph
from wandb.data_types import Image
from wandb.data_types import Plotly
from wandb.data_types import Video
from wandb.data_types import Audio
from wandb.data_types import Table
from wandb.data_types import Html
from wandb.data_types import Object3D
from wandb.data_types import Molecule
from wandb.data_types import Histogram

from wandb.wandb_agent import agent
from wandb.wandb_controller import sweep, controller

from wandb import superagent

# from wandb.core import *
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
api = InternalApi()
run = None
config = _preinit.PreInitObject("wandb.config")
summary = _preinit.PreInitObject("wandb.summary")
log = _preinit.PreInitCallable(
    "wandb.log", wandb_sdk.wandb_run.RunManaged.log
)
join = _preinit.PreInitCallable(
    "wandb.join", wandb_sdk.wandb_run.RunManaged.join
)
save = _preinit.PreInitCallable(
    "wandb.save", wandb_sdk.wandb_run.RunManaged.save
)
restore = _preinit.PreInitCallable(
    "wandb.restore", wandb_sdk.wandb_run.RunManaged.restore
)
use_artifact = _preinit.PreInitCallable(
    "wandb.use_artifact", wandb_sdk.wandb_run.RunManaged.use_artifact
)
log_artifact = _preinit.PreInitCallable(
    "wandb.log_artifact", wandb_sdk.wandb_run.RunManaged.log_artifact
)
# record of patched libraries
patched = {"tensorboard": [], "keras": [], "gym": []}

keras = _lazyloader.LazyLoader("wandb.keras", globals(), "wandb.integration.keras")
sklearn = _lazyloader.LazyLoader("wandb.sklearn", globals(), "wandb.sklearn")
tensorflow = _lazyloader.LazyLoader("wandb.tensorflow", globals(), "wandb.integration.tensorflow")
xgboost = _lazyloader.LazyLoader("wandb.xgboost", globals(), "wandb.integration.xgboost")
tensorboard = _lazyloader.LazyLoader("wandb.tensorboard", globals(), "wandb.integration.tensorboard")
gym = _lazyloader.LazyLoader("wandb.gym", globals(), "wandb.integration.gym")
lightgbm = _lazyloader.LazyLoader(
    "wandb.lightgbm", globals(), "wandb.integration.lightgbm"
)
docker = _lazyloader.LazyLoader("wandb.docker", globals(), "wandb.docker")
jupyter = _lazyloader.LazyLoader("wandb.jupyter", globals(), "wandb.jupyter")


def ensure_configured():
    global api
    api = InternalApi()


def set_trace():
    import pdb  # TODO: support other debuggers

    #  frame = sys._getframe().f_back
    pdb.set_trace()  # TODO: pass the parent stack...


__all__ = [
    "__version__",
    "init",
    "setup",
    "save",
    "sweep",
    "agent",
    "config",
    "log",
    "summary",
    "join",
    "Api",
    "Graph",
    "Image",
    "Plotly",
    "Video",
    "Audio",
    "Table",
    "Html",
    "Object3D",
    "Molecule",
    "Histogram",
]
