"""Functions for declaring overridable configuration for launch jobs."""

from typing import List, Optional

import wandb


def manage_config_file(
    path: str,
    include: Optional[List[str]] = None,
    exclude: Optional[List[str]] = None,
):
    r"""Declare an overridable configuration file for a launch job.

    If a new job version is created from the active run, the configuration file
    will be added to the job's inputs. If the job is launched and overrides
    have been provided for the configuration file, this function will detect
    the overrides from the environment and update the configuration file on disk.
    Note that these overrides will only be applied in ephemeral containers.

    `include` and `exclude` are lists of dot separated paths with the config.
    The paths are used to filter subtrees of the configuration file out of the
    job's inputs.

    For example, given the following configuration file:

        ```yaml
        model:
            name: resnet
            layers: 18
        training:
            epochs: 10
            batch_size: 32
        ```

    Passing `include=['model']` will only include the `model` subtree in the
    job's inputs. Passing `exclude=['model.layers']` will exclude the `layers`
    key from the `model` subtree. Note that `exclude` takes precedence over
    `include`.

    `.` is used as a separator for nested keys. If a key contains a `.`, it
    should be escaped with a backslash, e.g. `include=['model\.layers']`.

    Args:
        path (str): The path to the configuration file. This path must be
            relative and must not contain backwards traversal, i.e. `..`.
        include (List[str]): A list of keys to include in the configuration file.
        exclude (List[str]): A list of keys to exclude from the configuration file.
    """
    if not wandb_running():
        raise ValueError("This function must be called from a W&B run.")


def manage_wandb_config(
    include: Optional[List[str]] = None,
    exclude: Optional[List[str]] = None,
):
    r"""Declare wandb.config as an overridable configuration for a launch job.

    If a new job version is created from the active run, the run config
    (wandb.config) will become an overridable input of the job. If the job is
    launched and overrides have been provided for the run config, the overrides
    will be applied to the run config when `wandb.init` is called.

    `include` and `exclude` are lists of dot separated paths with the config.
    The paths are used to filter subtrees of the configuration file out of the
    job's inputs.

    For example, given the following run config contents:

        ```yaml
        model:
            name: resnet
            layers: 18
        training:
            epochs: 10
            batch_size: 32
        ```

    Passing `include=['model']` will only include the `model` subtree in the
    job's inputs. Passing `exclude=['model.layers']` will exclude the `layers`
    key from the `model` subtree. Note that `exclude` takes precedence over
    `include`.

    `.` is used as a separator for nested keys. If a key contains a `.`, it
    should be escaped with a backslash, e.g. `include=['model\.layers']`.

    Args:
        include (List[str]): A list of subtrees to include in the configuration.
        exclude (List[str]): A list of subtrees to exclude from the configuration.
    """
    if not wandb_running():
        raise ValueError("This function must be called from a W&B run.")


def wandb_running() -> bool:
    r"""Check if the function is being called from a W&B run.

    Returns:
        bool: True if the function is being called from a W&B run, False otherwise.
    """
    return wandb.run is not None


def _split_on_unesc_dot(path: str) -> List[str]:
    r"""Split a string on unescaped dots.

    Args:
        path (str): The string to split.

    Returns:
        List[str]: The split string.
    """
    parts = []
    part = ""
    i = 0
    while i < len(path):
        if path[i] == "\\":
            part += path[i + 1]
            i += 1
        elif path[i] == ".":
            parts.append(part)
            part = ""
        else:
            part += path[i]
        i += 1
    parts.append(part)
    return parts
