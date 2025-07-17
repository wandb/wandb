import inspect
import pickle
from functools import wraps
from pathlib import Path
from typing import Optional, Union

import wandb
from wandb.sdk.lib import telemetry as wb_telemetry

try:
    from metaflow import current
except ImportError as e:
    raise Exception(
        "Error: `metaflow` not installed >> This integration requires metaflow!  To fix, please `pip install -Uqq metaflow`"
    ) from e

try:
    from plum import dispatch
except ImportError as e:
    raise Exception(
        "Error: `plum-dispatch` not installed >> "
        "This integration requires plum-dispatch! To fix, please `pip install -Uqq plum-dispatch`"
    ) from e


try:
    import pandas as pd

    @dispatch
    def _wandb_use(
        name: str,
        data: pd.DataFrame,
        datasets=False,
        run=None,
        testing=False,
        *args,
        **kwargs,
    ):  # type: ignore
        if testing:
            return "datasets" if datasets else None

        if datasets:
            run.use_artifact(f"{name}:latest")
            wandb.termlog(f"Using artifact: {name} ({type(data)})")

    @dispatch
    def wandb_track(
        name: str,
        data: pd.DataFrame,
        datasets=False,
        run=None,
        testing=False,
        *args,
        **kwargs,
    ):
        if testing:
            return "pd.DataFrame" if datasets else None

        if datasets:
            artifact = wandb.Artifact(name, type="dataset")
            with artifact.new_file(f"{name}.parquet", "wb") as f:
                data.to_parquet(f, engine="pyarrow")
            run.log_artifact(artifact)
            wandb.termlog(f"Logging artifact: {name} ({type(data)})")

except ImportError:
    wandb.termwarn(
        "`pandas` not installed >> @wandb_log(datasets=True) may not auto log your dataset!"
    )

try:
    import torch
    import torch.nn as nn

    @dispatch
    def _wandb_use(
        name: str,
        data: nn.Module,
        models=False,
        run=None,
        testing=False,
        *args,
        **kwargs,
    ):  # type: ignore
        if testing:
            return "models" if models else None

        if models:
            run.use_artifact(f"{name}:latest")
            wandb.termlog(f"Using artifact: {name} ({type(data)})")

    @dispatch
    def wandb_track(
        name: str,
        data: nn.Module,
        models=False,
        run=None,
        testing=False,
        *args,
        **kwargs,
    ):
        if testing:
            return "nn.Module" if models else None

        if models:
            artifact = wandb.Artifact(name, type="model")
            with artifact.new_file(f"{name}.pkl", "wb") as f:
                torch.save(data, f)
            run.log_artifact(artifact)
            wandb.termlog(f"Logging artifact: {name} ({type(data)})")

except ImportError:
    wandb.termwarn(
        "`pytorch` not installed >> @wandb_log(models=True) may not auto log your model!"
    )

try:
    from sklearn.base import BaseEstimator

    @dispatch
    def _wandb_use(
        name: str,
        data: BaseEstimator,
        models=False,
        run=None,
        testing=False,
        *args,
        **kwargs,
    ):  # type: ignore
        if testing:
            return "models" if models else None

        if models:
            run.use_artifact(f"{name}:latest")
            wandb.termlog(f"Using artifact: {name} ({type(data)})")

    @dispatch
    def wandb_track(
        name: str,
        data: BaseEstimator,
        models=False,
        run=None,
        testing=False,
        *args,
        **kwargs,
    ):
        if testing:
            return "BaseEstimator" if models else None

        if models:
            artifact = wandb.Artifact(name, type="model")
            with artifact.new_file(f"{name}.pkl", "wb") as f:
                pickle.dump(data, f)
            run.log_artifact(artifact)
            wandb.termlog(f"Logging artifact: {name} ({type(data)})")

except ImportError:
    wandb.termwarn(
        "`sklearn` not installed >> @wandb_log(models=True) may not auto log your model!"
    )


class ArtifactProxy:
    def __init__(self, flow):
        # do this to avoid recursion problem with __setattr__
        self.__dict__.update(
            {
                "flow": flow,
                "inputs": {},
                "outputs": {},
                "base": set(dir(flow)),
                "params": {p: getattr(flow, p) for p in current.parameter_names},
            }
        )

    def __setattr__(self, key, val):
        self.outputs[key] = val
        return setattr(self.flow, key, val)

    def __getattr__(self, key):
        if key not in self.base and key not in self.outputs:
            self.inputs[key] = getattr(self.flow, key)
        return getattr(self.flow, key)


@dispatch
def wandb_track(
    name: str,
    data: Union[dict, list, set, str, int, float, bool],
    run=None,
    testing=False,
    *args,
    **kwargs,
):  # type: ignore
    if testing:
        return "scalar"

    run.log({name: data})


@dispatch
def wandb_track(
    name: str, data: Path, datasets=False, run=None, testing=False, *args, **kwargs
):
    if testing:
        return "Path" if datasets else None

    if datasets:
        artifact = wandb.Artifact(name, type="dataset")
        if data.is_dir():
            artifact.add_dir(data)
        elif data.is_file():
            artifact.add_file(data)
        run.log_artifact(artifact)
        wandb.termlog(f"Logging artifact: {name} ({type(data)})")


# this is the base case
@dispatch
def wandb_track(
    name: str, data, others=False, run=None, testing=False, *args, **kwargs
):
    if testing:
        return "generic" if others else None

    if others:
        artifact = wandb.Artifact(name, type="other")
        with artifact.new_file(f"{name}.pkl", "wb") as f:
            pickle.dump(data, f)
        run.log_artifact(artifact)
        wandb.termlog(f"Logging artifact: {name} ({type(data)})")


@dispatch
def wandb_use(name: str, data, *args, **kwargs):
    try:
        return _wandb_use(name, data, *args, **kwargs)
    except wandb.CommError:
        wandb.termwarn(
            f"This artifact ({name}, {type(data)}) does not exist in the wandb datastore!"
            f"If you created an instance inline (e.g. sklearn.ensemble.RandomForestClassifier), then you can safely ignore this"
            f"Otherwise you may want to check your internet connection!"
        )


@dispatch
def wandb_use(
    name: str, data: Union[dict, list, set, str, int, float, bool], *args, **kwargs
):  # type: ignore
    pass  # do nothing for these types


@dispatch
def _wandb_use(
    name: str, data: Path, datasets=False, run=None, testing=False, *args, **kwargs
):  # type: ignore
    if testing:
        return "datasets" if datasets else None

    if datasets:
        run.use_artifact(f"{name}:latest")
        wandb.termlog(f"Using artifact: {name} ({type(data)})")


@dispatch
def _wandb_use(name: str, data, others=False, run=None, testing=False, *args, **kwargs):  # type: ignore
    if testing:
        return "others" if others else None

    if others:
        run.use_artifact(f"{name}:latest")
        wandb.termlog(f"Using artifact: {name} ({type(data)})")


def coalesce(*arg):
    return next((a for a in arg if a is not None), None)


def wandb_log(
    func=None,
    /,
    datasets: bool = False,
    models: bool = False,
    others: bool = False,
    settings: Optional[wandb.Settings] = None,
):
    """Automatically log parameters and artifacts to W&B.

    This decorator can be applied to a flow, step, or both:

    - Decorating a step enables or disables logging within that step
    - Decorating a flow is equivalent to decorating all steps
    - Decorating a step after decorating its flow overwrites the flow decoration

    Args:
        func: The step method or flow class to decorate.
        datasets: Whether to log `pd.DataFrame` and `pathlib.Path`
            types. Defaults to False.
        models: Whether to log `nn.Module` and `sklearn.base.BaseEstimator`
            types. Defaults to False.
        others: If `True`, log anything pickle-able. Defaults to False.
        settings: Custom settings to pass to `wandb.init`.
            If `run_group` is `None`, it is set to `{flow_name}/{run_id}`.
            If `run_job_type` is `None`, it is set to `{run_job_type}/{step_name}`.
    """

    @wraps(func)
    def decorator(func):
        # If you decorate a class, apply the decoration to all methods in that class
        if inspect.isclass(func):
            cls = func
            for attr in cls.__dict__:
                if callable(getattr(cls, attr)):
                    if not hasattr(attr, "_base_func"):
                        setattr(cls, attr, decorator(getattr(cls, attr)))
            return cls

        # prefer the earliest decoration (i.e. method decoration overrides class decoration)
        if hasattr(func, "_base_func"):
            return func

        @wraps(func)
        def wrapper(self, *args, settings=settings, **kwargs):
            if not isinstance(settings, wandb.sdk.wandb_settings.Settings):
                settings = wandb.Settings()

            settings.update_from_dict(
                {
                    "run_group": coalesce(
                        settings.run_group, f"{current.flow_name}/{current.run_id}"
                    ),
                    "run_job_type": coalesce(settings.run_job_type, current.step_name),
                }
            )

            with wandb.init(settings=settings) as run:
                with wb_telemetry.context(run=run) as tel:
                    tel.feature.metaflow = True
                proxy = ArtifactProxy(self)
                run.config.update(proxy.params)
                func(proxy, *args, **kwargs)

                for name, data in proxy.inputs.items():
                    wandb_use(
                        name,
                        data,
                        datasets=datasets,
                        models=models,
                        others=others,
                        run=run,
                    )

                for name, data in proxy.outputs.items():
                    wandb_track(
                        name,
                        data,
                        datasets=datasets,
                        models=models,
                        others=others,
                        run=run,
                    )

        wrapper._base_func = func

        # Add for testing visibility
        wrapper._kwargs = {
            "datasets": datasets,
            "models": models,
            "others": others,
            "settings": settings,
        }
        return wrapper

    if func is None:
        return decorator
    else:
        return decorator(func)
