"""
Library public tests.
"""

import pytest

import wandb

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
from wandb.data_types import Classes
from wandb.data_types import JoinedTable

SYMBOLS_ROOT_DATATYPES = {
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
    "Classes",
    "JoinedTable",
}

SYMBOLS_ROOT_SDK = {
    "login",
    "init",
    "log",
    "log_artifact",
    "use_artifact",
    "summary",
    "config",
    "join",  # deprecate in favor of finish()
    "finish",
    "watch",
    "unwatch",
    "helper",
    "agent",
    "controller",
    "sweep",
}

# Look into these and see what we can remove / hide
SYMBOLS_ROOT_OTHER = {
    "AlertLevel",
    "Api",
    "Artifact",
    "CommError",
    "Config",
    "Error",
    "InternalApi",
    "PY3",
    "PublicApi",
    "START_TIME",
    "Settings",
    "TYPE_CHECKING",
    "UsageError",
    "absolute_import",
    "agents",
    "alert",
    "api",
    "apis",
    "compat",
    "data_types",
    "division",
    "docker",
    "dummy",
    "ensure_configured",
    "env",
    "errors",
    "filesync",
    "gym",
    "integration",
    "jupyter",
    "keras",
    "lightgbm",
    "old",
    "patched",
    "plot",
    "plot_table",
    "plots",
    "print_function",
    "proto",
    "restore",
    "run",
    "sacred",
    "sagemaker_auth",
    "save",
    "sdk",
    "set_trace",
    "setup",
    "sklearn",
    "superagent",
    "sys",
    "tensorboard",
    "tensorflow",
    "termerror",
    "termlog",
    "termsetup",
    "termwarn",
    "trigger",
    "unicode_literals",
    "util",
    "vendor",
    "visualize",
    "viz",
    "wandb",
    "wandb_agent",
    "wandb_controller",
    "wandb_lib",
    "wandb_sdk",
    "wandb_torch",
    "xgboost",
}


def test_library_root():
    symbol_list = dir(wandb)
    symbol_public_set = {s for s in symbol_list if not s.startswith("_")}
    print("symbols", symbol_public_set)
    symbol_unknown = (
        symbol_public_set
        - SYMBOLS_ROOT_DATATYPES
        - SYMBOLS_ROOT_SDK
        - SYMBOLS_ROOT_OTHER
    )
    assert symbol_unknown == set()


# normal run symbols
SYMBOLS_RUN = {
    "job_type",
    "group",
    "entity",
    "project",
    "name",
    "id",
    "join",  # deprecate in favor of finish()
    "finish",
    "watch",
    # "unwatch",  # this is missing, probably should have it or remove the root one
    "config",
    "config_static",
    "log",
    "log_artifact",
    "use_artifact",
    "alert",
    # "summary",   # really this should be here
    # mode stuff
    "mode",
    "disabled",
    "offline",
    "save",
    "restore",
    "notes",
    "tags",
}

# symbols having to do with resuming, we should clean this up
SYMBOLS_RUN_RESUME = {
    "starting_step",
    "step",
    "resumed",
}

# Look into these
SYMBOLS_RUN_OTHER = {
    "path",
    "plot_table",
    "get_project_url",
    "url",
    "get_url",
    "get_sweep_url",
    "start_time",
    "sweep_id",
    "dir",
    "project_name",
}


def test_library_run():
    Run = wandb.wandb_sdk.wandb_run.Run
    symbol_list = dir(Run)
    symbol_public_set = {s for s in symbol_list if not s.startswith("_")}
    print("symbols", symbol_public_set)
    symbol_unknown = (
        symbol_public_set - SYMBOLS_RUN - SYMBOLS_RUN_RESUME - SYMBOLS_RUN_OTHER
    )
    assert symbol_unknown == set()
