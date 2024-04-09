"""W&B Integration for Metaflow.

This integration lets users apply decorators to Metaflow flows and steps to automatically log parameters and artifacts to W&B by type dispatch.

- Decorating a step will enable or disable logging for certain types within that step
- Decorating the flow is equivalent to decorating all steps with a default
- Decorating a step after decorating the flow will overwrite the flow decoration

Examples can be found at wandb/wandb/functional_tests/metaflow
"""

import inspect
import pickle
from functools import wraps
from pathlib import Path

import wandb
from wandb.sdk.lib import telemetry as wb_telemetry

try:
    from metaflow import current
except ImportError as e:
    raise Exception(
        "Error: `metaflow` not installed >> This integration requires metaflow!  To fix, please `pip install -Uqq metaflow`"
    ) from e

try:
    from fastcore.all import typedispatch
except ImportError as e:
    raise Exception(
        "Error: `fastcore` not installed >> This integration requires fastcore!  To fix, please `pip install -Uqq fastcore`"
    ) from e


try:
    import pandas as pd

    @typedispatch  # noqa: F811
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

    @typedispatch  # noqa: F811
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
    print(
        "Warning: `pandas` not installed >> @wandb_log(datasets=True) may not auto log your dataset!"
    )

try:
    import torch
    import torch.nn as nn

    @typedispatch  # noqa: F811
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

    @typedispatch  # noqa: F811
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
    print(
        "Warning: `pytorch` not installed >> @wandb_log(models=True) may not auto log your model!"
    )

try:
    from sklearn.base import BaseEstimator

    @typedispatch  # noqa: F811
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

    @typedispatch  # noqa: F811
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
    print(
        "Warning: `sklearn` not installed >> @wandb_log(models=True) may not auto log your model!"
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


@typedispatch  # noqa: F811
def wandb_track(
    name: str,
    data: (dict, list, set, str, int, float, bool),
    run=None,
    testing=False,
    *args,
    **kwargs,
):  # type: ignore
    if testing:
        return "scalar"

    run.log({name: data})


@typedispatch  # noqa: F811
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
@typedispatch  # noqa: F811
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


@typedispatch
def wandb_use(name: str, data, *args, **kwargs):
    try:
        return _wandb_use(name, data, *args, **kwargs)
    except wandb.CommError:
        print(
            f"This artifact ({name}, {type(data)}) does not exist in the wandb datastore!"
            f"If you created an instance inline (e.g. sklearn.ensemble.RandomForestClassifier), then you can safely ignore this"
            f"Otherwise you may want to check your internet connection!"
        )


@typedispatch  # noqa: F811
def wandb_use(
    name: str, data: (dict, list, set, str, int, float, bool), *args, **kwargs
):  # type: ignore
    pass  # do nothing for these types


@typedispatch  # noqa: F811
def _wandb_use(
    name: str, data: Path, datasets=False, run=None, testing=False, *args, **kwargs
):  # type: ignore
    if testing:
        return "datasets" if datasets else None

    if datasets:
        run.use_artifact(f"{name}:latest")
        wandb.termlog(f"Using artifact: {name} ({type(data)})")


@typedispatch  # noqa: F811
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
    # /,  # py38 only
    datasets=False,
    models=False,
    others=False,
    settings=None,
):
    """Automatically log parameters and artifacts to W&B by type dispatch.

    This decorator can be applied to a flow, step, or both.
    - Decorating a step will enable or disable logging for certain types within that step
    - Decorating the flow is equivalent to decorating all steps with a default
    - Decorating a step after decorating the flow will overwrite the flow decoration

    Arguments:
        func: (`Callable`). The method or class being decorated (if decorating a step or flow respectively).
        datasets: (`bool`). If `True`, log datasets.  Datasets can be a `pd.DataFrame` or `pathlib.Path`.  The default value is `False`, so datasets are not logged.
        models: (`bool`). If `True`, log models.  Models can be a `nn.Module` or `sklearn.base.BaseEstimator`.  The default value is `False`, so models are not logged.
        others: (`bool`). If `True`, log anything pickle-able.  The default value is `False`, so files are not logged.
        settings: (`wandb.sdk.wandb_settings.Settings`). Custom settings passed to `wandb.init`.  The default value is `None`, and is the same as passing `wandb.Settings()`.  If `settings.run_group` is `None`, it will be set to `{flow_name}/{run_id}.  If `settings.run_job_type` is `None`, it will be set to `{run_job_type}/{step_name}`
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

            settings.update(
                run_group=coalesce(
                    settings.run_group, f"{current.flow_name}/{current.run_id}"
                ),
                source=wandb.sdk.wandb_settings.Source.INIT,
            )
            settings.update(
                run_job_type=coalesce(settings.run_job_type, current.step_name),
                source=wandb.sdk.wandb_settings.Source.INIT,
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
