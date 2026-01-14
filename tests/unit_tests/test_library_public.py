"""Library public tests.

*NOTE*: If you need to add a symbol, make sure this has been discussed and the name of the object or method is agreed upon.

Todo:
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
    "box3d",
    "Object3D",
    "Molecule",
    "Histogram",
    "Classes",
    "JoinedTable",
}

SYMBOLS_ROOT_SDK = {
    "ArtifactTTL",
    "Run",
    "login",
    "init",
    "log",
    "log_artifact",
    "use_artifact",
    "log_model",
    "use_model",
    "link_model",
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
    "automations",
    "beta",
    "catboost",
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
    "os",
    "setup",
    "sklearn",
    "sync",
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
    "annotations",
}

SYMBOLS_SERVICE = {"attach", "_attach", "teardown", "_teardown"}

SYMBOLS_ANALYTICS = {"analytics"}


def test_library_root():
    symbol_list = dir(wandb)
    symbol_public_set = {s for s in symbol_list if not s.startswith("_")}
    symbol_unknown = (
        symbol_public_set
        - SYMBOLS_ROOT_DATATYPES
        - SYMBOLS_ROOT_SDK
        - SYMBOLS_ROOT_OTHER
        - SYMBOLS_TYPING
        - SYMBOLS_SERVICE
        - SYMBOLS_ANALYTICS
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
    "finish",
    "watch",
    "unwatch",
    "config",
    "config_static",
    "log",
    "log_artifact",
    "link_artifact",
    "log_model",
    "use_model",
    "link_model",
    "upsert_artifact",
    "finish_artifact",
    "use_artifact",
    "log_code",
    "alert",
    "define_metric",
    # "summary",   # really this should be here
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
    "status",
}

# symbols having to do with resuming, we should clean this up
SYMBOLS_RUN_RESUME = {
    "starting_step",
    "step",
    "resumed",
}

# Look into these
SYMBOLS_RUN_OTHER = {
    "get_url",  # deprecated in favor of url
    "url",
    "get_project_url",  # deprecated in favor of project_url
    "project_url",
    "project_name",  # deprecated in favor of project
    "get_sweep_url",  # deprecated in favor of sweep_url
    "sweep_url",
    "sweep_id",
    "start_time",
    "path",
    "dir",
}


def test_library_run():
    symbol_list = dir(wandb.Run)
    symbol_public_set = {s for s in symbol_list if not s.startswith("_")}
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
    "merge_locked",
}


def test_library_config():
    Config = wandb.wandb_sdk.wandb_config.Config  # noqa: N806
    symbol_list = dir(Config)
    symbol_public_set = {s for s in symbol_list if not s.startswith("_")}
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
    "fork_from",
    "resume_from",
}


def test_library_init():
    init_params = set(inspect.signature(wandb.init).parameters)
    assert init_params == SYMBOLS_WANDB_INIT
