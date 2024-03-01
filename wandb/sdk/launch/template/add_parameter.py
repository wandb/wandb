"""Functions for adding parameters to a run template."""

from typing import Union

import wandb

from .config_file import ConfigFile
from .wandb_config import WandbConfigKeys


def add_parameter(
    parameter: Union[ConfigFile, WandbConfigKeys],
):
    """Add parameter to the run template derived from this computation, if any."""
    if wandb.run is None:
        raise ValueError("wandb.run is not initialized.")
    if isinstance(parameter, ConfigFile):
        return _add_config_file_parameter(parameter)
    elif isinstance(parameter, WandbConfigKeys):
        return _add_wandb_config_keys_parameter(parameter)
    else:
        raise ValueError(
            f"Expected a ConfigFile or WandbConfigKeys, but got {type(parameter)}."
        )


def _add_config_file_parameter(config_file: ConfigFile):
    """Add a config file parameter to the run template."""
    interface = wandb.run._backend.interface
    interface.publish_config_file_parameter(
        config_file.relpath,
        config_file.abspath,
        config_file.filename,
        config_file.include or [],
        config_file.ignore or [],
    )


def _add_wandb_config_keys_parameter(wandb_config_keys: WandbConfigKeys):
    """Add a wandb config keys parameter to the run template."""
    interface = wandb.run._backend.interface
    interface.publish_wandb_config_parameters(
        wandb_config_keys.ignore or [], wandb_config_keys.include or []
    )
