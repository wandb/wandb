import inspect
import pickle
from functools import wraps
from pathlib import Path
from typing import Optional, Union

import wandb
from wandb.sdk.lib import telemetry as wb_telemetry

from . import errors

try:
    from metaflow import current
except ImportError as e:
    raise Exception(
        "Error: `metaflow` not installed >> This integration requires metaflow!"
        " To fix, please `pip install -Uqq metaflow`"
    ) from e


try:
    from . import data_pandas
except errors.MissingDependencyError as e:
    e.warn()
    data_pandas = None

try:
    from . import data_pytorch
except errors.MissingDependencyError as e:
    e.warn()
    data_pytorch = None

try:
    from . import data_sklearn
except errors.MissingDependencyError as e:
    e.warn()
    data_sklearn = None


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


def _track_scalar(
    name: str,
    data: Union[dict, list, set, str, int, float, bool],
    run,
    testing: bool = False,
) -> Optional[str]:
    if testing:
        return "scalar"

    run.log({name: data})
    return None


def _track_path(
    name: str,
    data: Path,
    run,
    testing: bool = False,
) -> Optional[str]:
    if testing:
        return "Path"

    artifact = wandb.Artifact(name, type="dataset")
    if data.is_dir():
        artifact.add_dir(data)
    elif data.is_file():
        artifact.add_file(data)
    run.log_artifact(artifact)
    wandb.termlog(f"Logging artifact: {name} ({type(data)})")
    return None


def _track_generic(
    name: str,
    data,
    run,
    testing: bool = False,
) -> Optional[str]:
    if testing:
        return "generic"

    artifact = wandb.Artifact(name, type="other")
    with artifact.new_file(f"{name}.pkl", "wb") as f:
        pickle.dump(data, f)
    run.log_artifact(artifact)
    wandb.termlog(f"Logging artifact: {name} ({type(data)})")
    return None


def wandb_track(
    name: str,
    data,
    datasets: bool = False,
    models: bool = False,
    others: bool = False,
    run: Optional[wandb.Run] = None,
    testing: bool = False,
) -> Optional[str]:
    """Track data as wandb artifacts based on type and flags."""
    # Check for pandas DataFrame
    if data_pandas and data_pandas.is_dataframe(data) and datasets:
        return data_pandas.track_dataframe(name, data, run, testing)

    # Check for PyTorch Module
    if data_pytorch and data_pytorch.is_nn_module(data) and models:
        return data_pytorch.track_nn_module(name, data, run, testing)

    # Check for scikit-learn BaseEstimator
    if data_sklearn and data_sklearn.is_estimator(data) and models:
        return data_sklearn.track_estimator(name, data, run, testing)

    # Check for Path objects
    if isinstance(data, Path) and datasets:
        return _track_path(name, data, run, testing)

    # Check for scalar types
    if isinstance(data, (dict, list, set, str, int, float, bool)):
        return _track_scalar(name, data, run, testing)

    # Generic fallback
    if others:
        return _track_generic(name, data, run, testing)

    # No action taken
    return None


def wandb_use(
    name: str,
    data,
    datasets: bool = False,
    models: bool = False,
    others: bool = False,
    run=None,
    testing: bool = False,
) -> Optional[str]:
    """Use wandb artifacts based on data type and flags."""
    # Skip scalar types - nothing to use
    if isinstance(data, (dict, list, set, str, int, float, bool)):
        return None

    try:
        # Check for pandas DataFrame
        if data_pandas and data_pandas.is_dataframe(data) and datasets:
            return data_pandas.use_dataframe(name, run, testing)

        # Check for PyTorch Module
        elif data_pytorch and data_pytorch.is_nn_module(data) and models:
            return data_pytorch.use_nn_module(name, run, testing)

        # Check for scikit-learn BaseEstimator
        elif data_sklearn and data_sklearn.is_estimator(data) and models:
            return data_sklearn.use_estimator(name, run, testing)

        # Check for Path objects
        elif isinstance(data, Path) and datasets:
            return _use_path(name, data, run, testing)

        # Generic fallback
        elif others:
            return _use_generic(name, data, run, testing)

        else:
            return None

    except wandb.CommError:
        wandb.termwarn(
            f"This artifact ({name}, {type(data)}) does not exist in the wandb datastore!"
            " If you created an instance inline (e.g. sklearn.ensemble.RandomForestClassifier),"
            " then you can safely ignore this. Otherwise you may want to check your internet connection!"
        )
        return None


def _use_path(
    name: str,
    data: Path,
    run,
    testing: bool = False,
) -> Optional[str]:
    if testing:
        return "datasets"

    run.use_artifact(f"{name}:latest")
    wandb.termlog(f"Using artifact: {name} ({type(data)})")
    return None


def _use_generic(
    name: str,
    data,
    run,
    testing: bool = False,
) -> Optional[str]:
    if testing:
        return "others"

    run.use_artifact(f"{name}:latest")
    wandb.termlog(f"Using artifact: {name} ({type(data)})")
    return None


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
