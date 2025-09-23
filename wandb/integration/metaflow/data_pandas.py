"""Support for Pandas datatypes.

May raise MissingDependencyError on import.
"""

from __future__ import annotations

from typing_extensions import Any, TypeIs

import wandb

from . import errors

try:
    import pandas as pd
except ImportError as e:
    warning = (
        "`pandas` not installed >>"
        " @wandb_log(datasets=True) may not auto log your dataset!"
    )
    raise errors.MissingDependencyError(warning=warning) from e


def is_dataframe(data: Any) -> TypeIs[pd.DataFrame]:
    """Returns whether the data is a Pandas DataFrame."""
    return isinstance(data, pd.DataFrame)


def use_dataframe(
    name: str,
    run: wandb.Run | None,
    testing: bool = False,
) -> str | None:
    """Log a dependency on a DataFrame input.

    Args:
        name: Name of the input.
        run: The run to update.
        testing: True in unit tests.
    """
    if testing:
        return "datasets"
    assert run

    wandb.termlog(f"Using artifact: {name} (Pandas DataFrame)")
    run.use_artifact(f"{name}:latest")
    return None


def track_dataframe(
    name: str,
    data: pd.DataFrame,
    run: wandb.Run | None,
    testing: bool = False,
) -> str | None:
    """Log a DataFrame output as an artifact.

    Args:
        name: The output's name.
        data: The output's value.
        run: The run to update.
        testing: True in unit tests.
    """
    if testing:
        return "pd.DataFrame"
    assert run

    artifact = wandb.Artifact(name, type="dataset")
    with artifact.new_file(f"{name}.parquet", "wb") as f:
        data.to_parquet(f, engine="pyarrow")

    wandb.termlog(f"Logging artifact: {name} (Pandas DataFrame)")
    run.log_artifact(artifact)
    return None
