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
        if key not in self.base:
            self.inputs[key] = getattr(self.flow, key)
        return getattr(self.flow, key)


@typedispatch  # noqa: F811
def _wandb_log(name: str, data: pd.DataFrame, **kwargs):
    if kwargs["datasets"]:
        artifact = wandb.Artifact(name, type="dataset")
        with artifact.new_file(f"{name}.csv") as f:
            data.to_csv(f)
        kwargs["run"].log_artifact(artifact)


@typedispatch  # noqa: F811
def _wandb_log(name: str, data: nn.Module, **kwargs):
    if kwargs["models"]:
        artifact = wandb.Artifact(name, type="dataset")
        with artifact.new_file(f"{name}.pkl", "wb") as f:
            torch.save(data, f)
        kwargs["run"].log_artifact(artifact)


@typedispatch  # noqa: F811
def _wandb_log(name: str, data: BaseEstimator, **kwargs):
    if kwargs["models"]:
        artifact = wandb.Artifact(name, type="dataset")
        with artifact.new_file(f"{name}.pkl", "wb") as f:
            pickle.dump(data, f)
        kwargs["run"].log_artifact(artifact)


@typedispatch  # noqa: F811
def _wandb_log(name: str, data: (dict, list, set, str, int, float, bool), **kwargs):  # type: ignore
    kwargs["run"].log({name: data})


@typedispatch  # noqa: F811
def _wandb_use(name: str, data: (pd.DataFrame, nn.Module, BaseEstimator), **kwargs):  # type: ignore
    return kwargs["run"].use_artifact(f"{name}:latest")


def wandb_log(
    func=None,
    datasets=False,
    models=False,
    settings=wandb.Settings()
    # func=None, /, datasets=False, models=False, settings=wandb.Settings()  #py38 support only
):
    def decorator(func):
        @wraps(func)
        def wrapper(flow, *args, **kwargs):
            with wandb.init(settings=settings) as run:
                proxy = ArtifactProxy(flow)
                run.config.update(proxy.params)
                func(proxy, *args, **kwargs)

                print("=== LOGGING INPUTS ===")
                for name, data in proxy.inputs.items():
                    _wandb_use(name, data, run=run)
                    print(f"wandb: using artifact: {name} ({type(data)})")

                print("=== LOGGING OUTPUTS ===")
                for name, data in proxy.outputs.items():
                    _wandb_log(name, data, datasets=datasets, models=models, run=run)
                    print(f"wandb: logging artifact: {name} ({type(data)})")

        return wrapper

    if func is None:
        return decorator
    else:
        return decorator(func)
