"""Support for PyTorch datatypes.

May raise MissingDependencyError on import.
"""

from __future__ import annotations

from typing_extensions import Any, TypeIs

import wandb

from . import errors

try:
    import torch
    import torch.nn as nn
except ImportError as e:
    warning = (
        "`torch` (PyTorch) not installed >>"
        " @wandb_log(models=True) may not auto log your model!"
    )
    raise errors.MissingDependencyError(warning=warning) from e


def is_nn_module(data: Any) -> TypeIs[nn.Module]:
    """Returns whether the data is a PyTorch nn.Module."""
    return isinstance(data, nn.Module)


def use_nn_module(
    name: str,
    run: wandb.Run | None,
    testing: bool = False,
) -> str | None:
    """Log a dependency on a PyTorch model input.

    Args:
        name: Name of the input.
        run: The run to update.
        testing: True in unit tests.
    """
    if testing:
        return "models"
    assert run

    wandb.termlog(f"Using artifact: {name} (PyTorch nn.Module)")
    run.use_artifact(f"{name}:latest")
    return None


def track_nn_module(
    name: str,
    data: nn.Module,
    run: wandb.Run | None,
    testing: bool = False,
) -> str | None:
    """Log a PyTorch model output as an artifact.

    Args:
        name: The output's name.
        data: The output's value.
        run: The run to update.
        testing: True in unit tests.
    """
    if testing:
        return "nn.Module"
    assert run

    artifact = wandb.Artifact(name, type="model")
    with artifact.new_file(f"{name}.pkl", "wb") as f:
        torch.save(data, f)

    wandb.termlog(f"Logging artifact: {name} (PyTorch nn.Module)")
    run.log_artifact(artifact)
    return None
