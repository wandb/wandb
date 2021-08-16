import pickle
from functools import wraps

import wandb
from fastcore.all import typedispatch
from metaflow import current

# I think importing here is more appropriate than importing in the func?
try:
    import pandas as pd
except ImportError:
    print(
        "Warning: `pandas` not installed >> @wandb_log(datasets=True) may not auto log your dataset!"
    )

try:
    import torch
    import torch.nn as nn
except ImportError:
    print(
        "Warning: `pytorch` not installed >> @wandb_log(models=True) may not auto log your dataset!"
    )

try:
    from sklearn.base import BaseEstimator
except ImportError:
    print(
        "Warning: `sklearn` not installed >> @wandb_log(models=True) may not auto log your dataset!"
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
def wandb_track(name: str, data: (dict, list, set, str, int, float, bool), ctx):  # type: ignore
    ctx["run"].log({name: data})


@typedispatch  # noqa: F811
def wandb_track(name: str, data: Path, ctx):
    if ctx["datasets"]:
        artifact = wandb.Artifact(name, type="dataset")
        if data.is_dir():
            artifact.add_dir(data)
        elif data.is_file():
            artifact.add_file(data)
        ctx["run"].log_artifact(artifact)
        print(f"wandb: logging artifact: {name} ({type(data)})")


@typedispatch  # noqa: F811
def wandb_track(name: str, data: pd.DataFrame, ctx):
    if ctx["datasets"]:
        artifact = wandb.Artifact(name, type="dataset")
        with artifact.new_file(f"{name}.csv") as f:
            data.to_csv(f)
        ctx["run"].log_artifact(artifact)
        print(f"wandb: logging artifact: {name} ({type(data)})")


@typedispatch  # noqa: F811
def wandb_track(name: str, data: nn.Module, ctx):
    if ctx["models"]:
        artifact = wandb.Artifact(name, type="model")
        with artifact.new_file(f"{name}.pkl", "wb") as f:
            torch.save(data, f)
        ctx["run"].log_artifact(artifact)
        print(f"wandb: logging artifact: {name} ({type(data)})")


@typedispatch  # noqa: F811
def wandb_track(name: str, data: BaseEstimator, ctx):
    if ctx["models"]:
        artifact = wandb.Artifact(name, type="model")
        with artifact.new_file(f"{name}.pkl", "wb") as f:
            pickle.dump(data, f)
        ctx["run"].log_artifact(artifact)
        print(f"wandb: logging artifact: {name} ({type(data)})")


# this is the base case
@typedispatch  # noqa: F811
def wandb_track(name: str, data, ctx):
    if ctx["others"]:
        artifact = wandb.Artifact(name, type="other")
        with artifact.new_file(f"{name}.pkl", "wb") as f:
            pickle.dump(data, f)
        ctx["run"].log_artifact(artifact)
        print(f"wandb: logging artifact: {name} ({type(data)})")


@typedispatch
def wandb_use(name: str, data, ctx):
    try:
        _wandb_use(name, data, ctx)
    except wandb.CommError:
        print(
            f"This artifact ({name}, {type(data)}) does not exist in the wandb datastore!"
            f"If you created an instance inline (e.g. sklearn.ensemble.RandomForestClassifier), then you can safely ignore this"
            f"Otherwise you may want to check your internet connection!"
        )


@typedispatch  # noqa: F811
def wandb_use(name: str, data: (dict, list, set, str, int, float, bool), ctx):  # type: ignore
    pass  # do nothing for these types


@typedispatch  # noqa: F811
def _wandb_use(name: str, data: (nn.Module, BaseEstimator), ctx):  # type: ignore
    if ctx["models"]:
        ctx["run"].use_artifact(f"{name}:latest")
        print(f"wandb: using artifact: {name} ({type(data)})")


@typedispatch  # noqa: F811
def _wandb_use(name: str, data: (pd.DataFrame, Path), ctx):  # type: ignore
    if ctx["datasets"]:
        ctx["run"].use_artifact(f"{name}:latest")
        print(f"wandb: using artifact: {name} ({type(data)})")


@typedispatch  # noqa: F811
def _wandb_use(name: str, data, ctx):  # type: ignore
    if ctx["others"]:
        ctx["run"].use_artifact(f"{name}:latest")
        print(f"wandb: using artifact: {name} ({type(data)})")


def wandb_log(
    func=None,
    # /,  #  py38 support only
    datasets=False,
    models=False,
    others=False,
    settings=None,
):
    def decorator(func):
        # If you decorate a class, apply the decoration to all methods in that class
        if inspect.isclass(func):
            cls = func
            for attr in cls.__dict__:
                if callable(getattr(cls, attr)):
                    # print(f"calling deco on this {attr}")
                    if hasattr(attr, "_base_func"):
                        setattr(cls, attr, decorator(getattr(cls, attr)))
            return cls

        # prefer the latest decoration (i.e. method decoration overrides class decoration)
        if hasattr(func, "_base_func"):
            func = func._base_func

        @wraps(func)
        def wrapper(self, settings=settings, *args, **kwargs):
            if not settings:
                settings = wandb.Settings(
                    run_group=f"{current.flow_name}/{current.run_id}",
                    run_job_type=current.step_name,
                )
            with wandb.init(settings=settings) as run:
                proxy = ArtifactProxy(self)
                run.config.update(proxy.params)
                func(proxy, *args, **kwargs)
                ctx = {
                    "datasets": datasets,
                    "models": models,
                    "others": others,
                    "run": run,
                }

                print("=== LOGGING INPUTS ===")
                for name, data in proxy.inputs.items():
                    wandb_use(name, data, ctx)

                print("=== LOGGING OUTPUTS ===")
                for name, data in proxy.outputs.items():
                    wandb_track(name, data, ctx)

        wrapper._base_func = func
        return wrapper

    if func is None:
        return decorator
    else:
        return decorator(func)
