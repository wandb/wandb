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

For examples usage, see github.com/wandb/examples
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

__version__ = "0.10.21"

# Used with pypi checks and other messages related to pip
_wandb_module = "wandb"

import sys

from wandb.errors import Error

# This needs to be early as other modules call it.
from wandb.errors.term import termsetup, termlog, termerror, termwarn

PY3 = sys.version_info.major == 3 and sys.version_info.minor >= 6
TYPE_CHECKING = False  # type: bool
if PY3:
    TYPE_CHECKING = True
    from wandb import sdk as wandb_sdk
else:
    from wandb import sdk_py27 as wandb_sdk

import wandb

wandb.wandb_lib = wandb_sdk.lib

init = wandb_sdk.init
setup = wandb_sdk.setup
save = wandb_sdk.save
watch = wandb_sdk.watch
unwatch = wandb_sdk.unwatch
finish = wandb_sdk.finish
join = finish
login = wandb_sdk.login
helper = wandb_sdk.helper
Artifact = wandb_sdk.Artifact
AlertLevel = wandb_sdk.AlertLevel
Settings = wandb_sdk.Settings
Config = wandb_sdk.Config

from wandb.apis import InternalApi, PublicApi
from wandb.errors.error import CommError, UsageError

_preinit = wandb_lib.preinit
_lazyloader = wandb_lib.lazyloader
from wandb import wandb_torch
from wandb import util

# Move this (keras.__init__ expects it at top level)
from wandb.data_types import Graph
from wandb.data_types import Image
from wandb.data_types import Plotly

# from wandb.data_types import Bokeh # keeping out of top level for now since Bokeh plots have poor UI
from wandb.data_types import Video
from wandb.data_types import Audio
from wandb.data_types import Table
from wandb.data_types import Html
from wandb.data_types import Object3D
from wandb.data_types import Molecule
from wandb.data_types import Histogram
from wandb.data_types import Classes
from wandb.data_types import JoinedTable

from wandb.wandb_agent import agent
from wandb.wandb_controller import sweep, controller

from wandb import superagent

# from wandb.core import *
from wandb.viz import visualize
from wandb import plot
from wandb import plots  # deprecating this
from wandb.integration.sagemaker import sagemaker_auth


# Used to make sure we don't use some code in the incorrect process context
_IS_INTERNAL_PROCESS = False


def _set_internal_process(disable=False):
    global _IS_INTERNAL_PROCESS
    if _IS_INTERNAL_PROCESS is None:
        return
    if disable:
        _IS_INTERNAL_PROCESS = None
        return
    _IS_INTERNAL_PROCESS = True


def _assert_is_internal_process():
    if _IS_INTERNAL_PROCESS is None:
        return
    assert _IS_INTERNAL_PROCESS


def _assert_is_user_process():
    if _IS_INTERNAL_PROCESS is None:
        return
    assert not _IS_INTERNAL_PROCESS


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
config = _preinit.PreInitCallable(
    _preinit.PreInitObject("wandb.config"), wandb_sdk.wandb_config.Config
)
summary = _preinit.PreInitCallable(
    _preinit.PreInitObject("wandb.summary"), wandb_sdk.wandb_summary.Summary
)
log = _preinit.PreInitCallable("wandb.log", wandb_sdk.wandb_run.Run.log)
save = _preinit.PreInitCallable("wandb.save", wandb_sdk.wandb_run.Run.save)
restore = wandb_sdk.wandb_run.restore
use_artifact = _preinit.PreInitCallable(
    "wandb.use_artifact", wandb_sdk.wandb_run.Run.use_artifact
)
log_artifact = _preinit.PreInitCallable(
    "wandb.log_artifact", wandb_sdk.wandb_run.Run.log_artifact
)
_define_metric = _preinit.PreInitCallable(
    "wandb._define_metric", wandb_sdk.wandb_run.Run._define_metric
)
plot_table = _preinit.PreInitCallable(
    "wandb.plot_table", wandb_sdk.wandb_run.Run.plot_table
)
alert = _preinit.PreInitCallable("wandb.alert", wandb_sdk.wandb_run.Run.alert)

# record of patched libraries
patched = {"tensorboard": [], "keras": [], "gym": []}

keras = _lazyloader.LazyLoader("wandb.keras", globals(), "wandb.integration.keras")
sklearn = _lazyloader.LazyLoader("wandb.sklearn", globals(), "wandb.sklearn")
tensorflow = _lazyloader.LazyLoader(
    "wandb.tensorflow", globals(), "wandb.integration.tensorflow"
)
xgboost = _lazyloader.LazyLoader(
    "wandb.xgboost", globals(), "wandb.integration.xgboost"
)
tensorboard = _lazyloader.LazyLoader(
    "wandb.tensorboard", globals(), "wandb.integration.tensorboard"
)
gym = _lazyloader.LazyLoader("wandb.gym", globals(), "wandb.integration.gym")
lightgbm = _lazyloader.LazyLoader(
    "wandb.lightgbm", globals(), "wandb.integration.lightgbm"
)
docker = _lazyloader.LazyLoader("wandb.docker", globals(), "wandb.docker")
jupyter = _lazyloader.LazyLoader("wandb.jupyter", globals(), "wandb.jupyter")
sacred = _lazyloader.LazyLoader("wandb.sacred", globals(), "wandb.integration.sacred")


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
