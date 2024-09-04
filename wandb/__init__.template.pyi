"""Use wandb to track machine learning work.

Train and fine-tune models, manage models from experimentation to production.

For guides and examples, see https://docs.wandb.ai.

For scripts and interactive notebooks, see https://github.com/wandb/examples.

For reference documentation, see https://docs.wandb.com/ref/python.
"""

__all__ = (
    "__version__",
    "init",
    "finish",
    "setup",
    "login",
    "save",
    "sweep",
    "controller",
    "agent",
    "config",
    "log",
    "summary",
    "Api",
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
    "ArtifactTTL",
    "log_artifact",
    "use_artifact",
    "log_model",
    "use_model",
    "link_model",
    "define_metric",
    "Error",
    "termsetup",
    "termlog",
    "termerror",
    "termwarn",
    "Artifact",
    "Settings",
    "teardown",
)

import os
from typing import Any, Callable, Dict, List, Literal, Optional, Sequence, Union

from wandb.analytics import Sentry as _Sentry
from wandb.apis import InternalApi, PublicApi
from wandb.data_types import (
    Audio,
    Graph,
    Histogram,
    Html,
    Image,
    Molecule,
    Object3D,
    Plotly,
    Table,
    Video,
    box3d,
)
from wandb.errors import Error
from wandb.errors.term import termerror, termlog, termsetup, termwarn
from wandb.sdk import Artifact, Settings, wandb_config, wandb_metric, wandb_summary
from wandb.sdk.artifacts.artifact_ttl import ArtifactTTL
from wandb.sdk.interface.interface import PolicyName
from wandb.sdk.lib.paths import FilePathStr, StrPath
from wandb.sdk.wandb_run import Run
from wandb.sdk.wandb_setup import _WandbSetup
from wandb.wandb_controller import _WandbController

__version__: str = "0.17.9.dev1"

run: Optional[Run] = None
config = wandb_config.Config
summary = wandb_summary.Summary
Api = PublicApi
api = InternalApi()
_sentry = _Sentry()

# record of patched libraries
patched = {"tensorboard": [], "keras": [], "gym": []}  # type: ignore

def setup(
    settings: Optional[Settings] = None,
) -> Optional[_WandbSetup]:
    """<sdk/wandb_setup.py::setup>"""
    ...

def teardown(exit_code: Optional[int] = None) -> None:
    """<sdk/wandb_setup.py::teardown>"""
    ...

def init(
    job_type: Optional[str] = None,
    dir: Optional[StrPath] = None,
    config: Union[Dict, str, None] = None,
    project: Optional[str] = None,
    entity: Optional[str] = None,
    reinit: Optional[bool] = None,
    tags: Optional[Sequence] = None,
    group: Optional[str] = None,
    name: Optional[str] = None,
    notes: Optional[str] = None,
    magic: Optional[Union[dict, str, bool]] = None,
    config_exclude_keys: Optional[List[str]] = None,
    config_include_keys: Optional[List[str]] = None,
    anonymous: Optional[str] = None,
    mode: Optional[str] = None,
    allow_val_change: Optional[bool] = None,
    resume: Optional[Union[bool, str]] = None,
    force: Optional[bool] = None,
    tensorboard: Optional[bool] = None,  # alias for sync_tensorboard
    sync_tensorboard: Optional[bool] = None,
    monitor_gym: Optional[bool] = None,
    save_code: Optional[bool] = None,
    id: Optional[str] = None,
    fork_from: Optional[str] = None,
    resume_from: Optional[str] = None,
    settings: Union[Settings, Dict[str, Any], None] = None,
) -> Run:
    """<sdk/wandb_init.py::init>"""
    ...

def finish(exit_code: Optional[int] = None, quiet: Optional[bool] = None) -> None:
    """<sdk/wandb_run.py::finish>"""
    ...

def login(
    anonymous: Optional[Literal["must", "allow", "never"]] = None,
    key: Optional[str] = None,
    relogin: Optional[bool] = None,
    host: Optional[str] = None,
    force: Optional[bool] = None,
    timeout: Optional[int] = None,
    verify: bool = False,
) -> bool:
    """<sdk/wandb_login.py::login>"""
    ...

def log(
    data: Dict[str, Any],
    step: Optional[int] = None,
    commit: Optional[bool] = None,
    sync: Optional[bool] = None,
) -> None:
    """<sdk/wandb_run.py::Run::log>"""
    ...

def save(
    glob_str: Optional[Union[str, os.PathLike]] = None,
    base_path: Optional[Union[str, os.PathLike]] = None,
    policy: PolicyName = "live",
) -> Union[bool, List[str]]:
    """<sdk/wandb_run.py::Run::save>"""
    ...

def sweep(
    sweep: Union[dict, Callable],
    entity: Optional[str] = None,
    project: Optional[str] = None,
    prior_runs: Optional[List[str]] = None,
) -> str:
    """<sdk/wandb_sweep.py::sweep>"""
    ...

def controller(
    sweep_id_or_config: Optional[Union[str, Dict]] = None,
    entity: Optional[str] = None,
    project: Optional[str] = None,
) -> _WandbController:
    """<sdk/wandb_sweep.py::controller>"""
    ...

def agent(
    sweep_id: str,
    function: Optional[Callable] = None,
    entity: Optional[str] = None,
    project: Optional[str] = None,
    count: Optional[int] = None,
) -> None:
    """<wandb_agent.py::agent>"""
    ...

def define_metric(
    name: str,
    step_metric: Union[str, wandb_metric.Metric, None] = None,
    step_sync: Optional[bool] = None,
    hidden: Optional[bool] = None,
    summary: Optional[str] = None,
    goal: Optional[str] = None,
    overwrite: Optional[bool] = None,
) -> wandb_metric.Metric:
    """<sdk/wandb_run.py::Run::define_metric>"""
    ...

def log_artifact(
    artifact_or_path: Union[Artifact, StrPath],
    name: Optional[str] = None,
    type: Optional[str] = None,
    aliases: Optional[List[str]] = None,
) -> Artifact:
    """<sdk/wandb_run.py::Run::log_artifact>"""
    ...

def use_artifact(
    artifact_or_name: Union[str, Artifact],
    type: Optional[str] = None,
    aliases: Optional[List[str]] = None,
    use_as: Optional[str] = None,
) -> Artifact:
    """<sdk/wandb_run.py::Run::use_artifact>"""
    ...

def log_model(
    path: StrPath,
    name: Optional[str] = None,
    aliases: Optional[List[str]] = None,
) -> None:
    """<sdk/wandb_run.py::Run::log_model>"""
    ...

def use_model(name: str) -> FilePathStr:
    """<sdk/wandb_run.py::Run::use_model>"""
    ...

def link_model(
    path: StrPath,
    registered_model_name: str,
    name: Optional[str] = None,
    aliases: Optional[List[str]] = None,
) -> None:
    """<sdk/wandb_run.py::Run::link_model>"""
    ...
