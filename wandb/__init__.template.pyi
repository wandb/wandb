"""Use wandb to track machine learning work.

Train and fine-tune models, manage models from experimentation to production.

For guides and examples, see https://docs.wandb.ai.

For scripts and interactive notebooks, see https://github.com/wandb/examples.

For reference documentation, see https://docs.wandb.com/ref/python.
"""

from __future__ import annotations

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
    "watch",
    "unwatch",
    "plot",
    "plot_table",
    "restore",
)

import os
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    Literal,
    Optional,
    Sequence,
    TextIO,
    Union,
)

import wandb.plot as plot
from wandb.analytics import Sentry
from wandb.apis import InternalApi
from wandb.apis import PublicApi as Api
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

if TYPE_CHECKING:
    import torch  # type: ignore [import-not-found]

    import wandb
    from wandb.plot import CustomChart

__version__: str = "0.19.11.dev1"

run: Run | None
config: wandb_config.Config
summary: wandb_summary.Summary

# private attributes
_sentry: Sentry
api: InternalApi
patched: Dict[str, List[Callable]]

def require(
    requirement: str | Iterable[str] | None = None,
    experiment: str | Iterable[str] | None = None,
) -> None:
    """<sdk/wandb_require.py::require>"""
    ...

def setup(settings: Settings | None = None) -> _WandbSetup:
    """<sdk/wandb_setup.py::setup>"""
    ...

def teardown(exit_code: int | None = None) -> None:
    """<sdk/wandb_setup.py::teardown>"""
    ...

def init(
    entity: str | None = None,
    project: str | None = None,
    dir: StrPath | None = None,
    id: str | None = None,
    name: str | None = None,
    notes: str | None = None,
    tags: Sequence[str] | None = None,
    config: dict[str, Any] | str | None = None,
    config_exclude_keys: list[str] | None = None,
    config_include_keys: list[str] | None = None,
    allow_val_change: bool | None = None,
    group: str | None = None,
    job_type: str | None = None,
    mode: Literal["online", "offline", "disabled"] | None = None,
    force: bool | None = None,
    anonymous: Literal["never", "allow", "must"] | None = None,
    reinit: (
        bool
        | Literal[
            None,
            "default",
            "return_previous",
            "finish_previous",
            "create_new",
        ]
    ) = None,
    resume: bool | Literal["allow", "never", "must", "auto"] | None = None,
    resume_from: str | None = None,
    fork_from: str | None = None,
    save_code: bool | None = None,
    tensorboard: bool | None = None,
    sync_tensorboard: bool | None = None,
    monitor_gym: bool | None = None,
    settings: Settings | dict[str, Any] | None = None,
) -> Run:
    """<sdk/wandb_init.py::init>"""
    ...

def finish(
    exit_code: int | None = None,
    quiet: bool | None = None,
) -> None:
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
    referrer: Optional[str] = None,
) -> bool:
    """<sdk/wandb_login.py::login>"""
    ...

def log(
    data: dict[str, Any],
    step: int | None = None,
    commit: bool | None = None,
    sync: bool | None = None,
) -> None:
    """<sdk/wandb_run.py::Run::log>"""
    ...

def save(
    glob_str: str | os.PathLike | None = None,
    base_path: str | os.PathLike | None = None,
    policy: PolicyName = "live",
) -> bool | list[str]:
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
    step_metric: str | wandb_metric.Metric | None = None,
    step_sync: bool | None = None,
    hidden: bool | None = None,
    summary: str | None = None,
    goal: str | None = None,
    overwrite: bool | None = None,
) -> wandb_metric.Metric:
    """<sdk/wandb_run.py::Run::define_metric>"""
    ...

def log_artifact(
    artifact_or_path: Artifact | StrPath,
    name: str | None = None,
    type: str | None = None,
    aliases: list[str] | None = None,
    tags: list[str] | None = None,
) -> Artifact:
    """<sdk/wandb_run.py::Run::log_artifact>"""
    ...

def use_artifact(
    artifact_or_name: str | Artifact,
    type: str | None = None,
    aliases: list[str] | None = None,
    use_as: str | None = None,
) -> Artifact:
    """<sdk/wandb_run.py::Run::use_artifact>"""
    ...

def log_model(
    path: StrPath,
    name: str | None = None,
    aliases: list[str] | None = None,
) -> None:
    """<sdk/wandb_run.py::Run::log_model>"""
    ...

def use_model(name: str) -> FilePathStr:
    """<sdk/wandb_run.py::Run::use_model>"""
    ...

def link_model(
    path: StrPath,
    registered_model_name: str,
    name: str | None = None,
    aliases: list[str] | None = None,
) -> Artifact | None:
    """<sdk/wandb_run.py::Run::link_model>"""
    ...

def plot_table(
    vega_spec_name: str,
    data_table: wandb.Table,
    fields: dict[str, Any],
    string_fields: dict[str, Any] | None = None,
    split_table: bool = False,
) -> CustomChart:
    """<plot/custom_chart.py::plot_table>"""
    ...

def watch(
    models: torch.nn.Module | Sequence[torch.nn.Module],
    criterion: torch.F | None = None,
    log: Literal["gradients", "parameters", "all"] | None = "gradients",
    log_freq: int = 1000,
    idx: int | None = None,
    log_graph: bool = False,
) -> None:
    """<sdk/wandb_run.py::Run::watch>"""
    ...

def unwatch(
    models: torch.nn.Module | Sequence[torch.nn.Module] | None = None,
) -> None:
    """<sdk/wandb_run.py::Run::unwatch>"""
    ...

def restore(
    name: str,
    run_path: str | None = None,
    replace: bool = False,
    root: str | None = None,
) -> None | TextIO:
    """<sdk/wandb_run.py::restore>"""
    ...
