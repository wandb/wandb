"""Use wandb to track machine learning work.

The most commonly used functions/objects are:
  - wandb.init — initialize a new run at the top of your training script
  - wandb.config — track hyperparameters and metadata
  - wandb.log — log metrics and media over time within your training loop

For guides and examples, see https://docs.wandb.com/guides.

For scripts and interactive notebooks, see https://github.com/wandb/examples.

For reference documentation, see https://docs.wandb.com/ref/python.
"""
__version__ = "0.12.16"

# Used with pypi checks and other messages related to pip
_wandb_module = "wandb"

from typing import Optional

from wandb.errors import Error

# This needs to be early as other modules call it.
from wandb.errors.term import termsetup, termlog, termerror, termwarn

from wandb import sdk as wandb_sdk

import wandb

wandb.wandb_lib = wandb_sdk.lib

init = wandb_sdk.init
setup = wandb_sdk.setup
_attach = wandb_sdk._attach
_teardown = wandb_sdk.teardown
save = wandb_sdk.save
watch = wandb_sdk.watch
unwatch = wandb_sdk.unwatch
finish = wandb_sdk.finish
join = finish
login = wandb_sdk.login
helper = wandb_sdk.helper
sweep = wandb_sdk.sweep
controller = wandb_sdk.controller
require = wandb_sdk.require
Artifact = wandb_sdk.Artifact
AlertLevel = wandb_sdk.AlertLevel
Settings = wandb_sdk.Settings
Config = wandb_sdk.Config

from wandb.apis import InternalApi, PublicApi
from wandb.errors import CommError, UsageError

_preinit = wandb.wandb_lib.preinit
_lazyloader = wandb.wandb_lib.lazyloader

# Call import module hook to setup any needed require hooks
wandb.sdk.wandb_require._import_module_hook()

from wandb import wandb_torch

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

# from wandb.core import *
from wandb.viz import visualize
from wandb import plot
from wandb import plots  # deprecating this
from wandb.integration.sagemaker import sagemaker_auth
from wandb.sdk.internal import profiler


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
run: Optional["wandb.sdk.wandb_run.Run"] = None
config = _preinit.PreInitObject("wandb.config", wandb_sdk.wandb_config.Config)
summary = _preinit.PreInitObject("wandb.summary", wandb_sdk.wandb_summary.Summary)
log = _preinit.PreInitCallable("wandb.log", wandb_sdk.wandb_run.Run.log)
save = _preinit.PreInitCallable("wandb.save", wandb_sdk.wandb_run.Run.save)
restore = wandb_sdk.wandb_run.restore
use_artifact = _preinit.PreInitCallable(
    "wandb.use_artifact", wandb_sdk.wandb_run.Run.use_artifact
)
log_artifact = _preinit.PreInitCallable(
    "wandb.log_artifact", wandb_sdk.wandb_run.Run.log_artifact
)
define_metric = _preinit.PreInitCallable(
    "wandb.define_metric", wandb_sdk.wandb_run.Run.define_metric
)

mark_preempting = _preinit.PreInitCallable(
    "wandb.mark_preempting", wandb_sdk.wandb_run.Run.mark_preempting
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
catboost = _lazyloader.LazyLoader(
    "wandb.catboost", globals(), "wandb.integration.catboost"
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


def load_ipython_extension(ipython):
    ipython.register_magics(wandb.jupyter.WandBMagics)


if wandb_sdk.lib.ipython.in_jupyter():
    from IPython import get_ipython

    load_ipython_extension(get_ipython())

__all__ = [
    "__version__",
    "init",
    "setup",
    "save",
    "sweep",
    "controller",
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
