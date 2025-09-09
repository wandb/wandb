"""Support for sklearn datatypes.

May raise MissingDependencyError on import.
"""

from __future__ import annotations

import pickle

from typing_extensions import Any, TypeIs

import wandb

from . import errors

try:
    from sklearn.base import BaseEstimator
except ImportError as e:
    warning = (
        "`sklearn` not installed >>"
        " @wandb_log(models=True) may not auto log your model!"
    )
    raise errors.MissingDependencyError(warning=warning) from e


def is_estimator(data: Any) -> TypeIs[BaseEstimator]:
    """Returns whether the data is an sklearn BaseEstimator."""
    return isinstance(data, BaseEstimator)


def use_estimator(
    name: str,
    run: wandb.Run | None,
    testing: bool = False,
) -> str | None:
    """Log a dependency on an sklearn estimator.

    Args:
        name: Name of the input.
        run: The run to update.
        testing: True in unit tests.
    """
    if testing:
        return "models"
    assert run

    wandb.termlog(f"Using artifact: {name} (sklearn BaseEstimator)")
    run.use_artifact(f"{name}:latest")
    return None


def track_estimator(
    name: str,
    data: BaseEstimator,
    run: wandb.Run | None,
    testing: bool = False,
) -> str | None:
    """Log an sklearn estimator output as an artifact.

    Args:
        name: The output's name.
        data: The output's value.
        run: The run to update.
        testing: True in unit tests.
    """
    if testing:
        return "BaseEstimator"
    assert run

    artifact = wandb.Artifact(name, type="model")
    with artifact.new_file(f"{name}.pkl", "wb") as f:
        pickle.dump(data, f)

    wandb.termlog(f"Logging artifact: {name} (sklearn BaseEstimator)")
    run.log_artifact(artifact)
    return None
