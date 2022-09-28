"""
Library public tests.

*NOTE*: If you need to add a symbol, make sure this has been discussed and the name of the object or method is agreed upon.

TODO:
    - clean up / hide symbols, which shouldn't be public
    - deprecate ones that were public but we want to remove

"""
import inspect

import wandb

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
    "define_metric",
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
    "mark_preempting",
    "load_ipython_extension",
    "require",
    "profiler",
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
    "PublicApi",
    "START_TIME",
    "Settings",
    "UsageError",
    "absolute_import",
    "agents",
    "alert",
    "api",
    "apis",
    "beta",
    "catboost",
    "data_types",
    "division",
    "docker",
    "sdk_py27",
    "wandb.docker",  # what is this?
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
    "sync",
    "sys",
    "tensorboard",
    "wandb.tensorboard",  # TODO: much like wandb.docker, this mysteriously failed in CI...?
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
    "workflows",
    "xgboost",
    "cli",
}

SYMBOLS_TYPING = {
    "Any",
    "AnyStr",
    "Callable",
    "ClassVar",
    "Dict",
    "List",
    "Optional",
    "Set",
    "Tuple",
    "Type",
    "TypeVar",
    "Union",
}

SYMBOLS_SERVICE = {"attach", "detach", "teardown"}


def test_library_root():
    symbol_list = dir(wandb)
    symbol_public_set = {s for s in symbol_list if not s.startswith("_")}
    print("symbols", symbol_public_set)
    symbol_unknown = (
        symbol_public_set
        - SYMBOLS_ROOT_DATATYPES
        - SYMBOLS_ROOT_SDK
        - SYMBOLS_ROOT_OTHER
        - SYMBOLS_TYPING
        - SYMBOLS_SERVICE
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
    "unwatch",
    "config",
    "config_static",
    "log",
    "log_artifact",
    "link_artifact",
    "upsert_artifact",
    "finish_artifact",
    "use_artifact",
    "log_code",
    "alert",
    "define_metric",
    # "summary",   # really this should be here
    # mode stuff
    "mode",
    "disabled",
    "offline",
    "save",
    "restore",
    "notes",
    "tags",
    "mark_preempting",
    "to_html",
    "display",
    "settings",
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
    Run = wandb.wandb_sdk.wandb_run.Run  # noqa: N806
    symbol_list = dir(Run)
    symbol_public_set = {s for s in symbol_list if not s.startswith("_")}
    print("symbols", symbol_public_set)
    symbol_unknown = (
        symbol_public_set
        - SYMBOLS_RUN
        - SYMBOLS_RUN_RESUME
        - SYMBOLS_RUN_OTHER
        - SYMBOLS_TYPING
        - SYMBOLS_SERVICE
    )
    assert symbol_unknown == set()


SYMBOLS_CONFIG = {
    "get",
    "update",
    "setdefaults",
    "items",
    "keys",
}

# Look into these
SYMBOLS_CONFIG_OTHER = {
    "as_dict",
    "update_locked",
    "persist",
}


def test_library_config():
    Config = wandb.wandb_sdk.wandb_config.Config  # noqa: N806
    symbol_list = dir(Config)
    symbol_public_set = {s for s in symbol_list if not s.startswith("_")}
    print("symbols", symbol_public_set)
    symbol_unknown = (
        symbol_public_set - SYMBOLS_CONFIG - SYMBOLS_CONFIG_OTHER - SYMBOLS_TYPING
    )
    assert symbol_unknown == set()


SYMBOLS_WANDB_INIT = {
    "force",
    "settings",
    "project",
    "tensorboard",
    "config",
    "allow_val_change",
    "id",
    "monitor_gym",
    "magic",
    "group",
    "resume",
    "dir",
    "anonymous",
    "mode",
    "config_exclude_keys",
    "tags",
    "name",
    "entity",
    "sync_tensorboard",
    "config_include_keys",
    "save_code",
    "notes",
    "job_type",
    "reinit",
}


def test_library_init():
    init_params = set(inspect.signature(wandb.init).parameters)
    print("init_params", init_params)
    assert init_params == SYMBOLS_WANDB_INIT
