"""Functions for declaring overridable configuration for launch jobs."""

from typing import List, Optional


def manage_config_file(
    path: str,
    include: Optional[List[str]] = None,
    exclude: Optional[List[str]] = None,
):
    """Declare an overridable configuration file for a launch job.

    If a new job version is created from the active run, the configuration file
    will be added to the job's inputs. If the job is launched and overrides
    have been provided for the configuration file, this function will detect
    the overrides from the environment and update the configuration file on disk.
    Note that these overrides will only be applied in ephemeral containers.

    Args:
        path (str): The path to the configuration file.
        include (List[str]): A list of keys to include in the configuration file.
        exclude (List[str]): A list of keys to exclude from the configuration file.
    """


def manage_wandb_config(
    include: Optional[List[str]] = None,
    exclude: Optional[List[str]] = None,
):
    """Declare wandb.config as an overridable configuration for a launch job.

    If a new job version is created from the active run, the run config
    (wandb.config) will become an overridable input of the job. If the job is
    launched and overrides have been provided for the run config, the overrides
    will be applied to the run config when `wandb.init` is called.

    Args:
        include (List[str]): A list of keys to include in the configuration.
        exclude (List[str]): A list of keys to exclude from the configuration.
    """
