"""Functions for declaring overridable configuration for launch jobs."""

import os
import shutil
import tempfile
from typing import List, Optional

import wandb

from ..errors import LaunchError
from .files import config_path_is_valid, override_file


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

    Raises:
        LaunchError: If the path is not valid, or if there is no active run.
    """
    if wandb.run is None:
        raise LaunchError("This function must be called from a W&B run.")
    config_path_is_valid(path)
    override_file(path)
    with tempfile.TemporaryDirectory() as tmp:
        config_dir = os.path.join(tmp, "configs")
        dest = os.path.join(config_dir, path)
        os.mkdir(config_dir)
        shutil.copy(path, dest)
        wandb.save(dest, base_path=tmp)
    assert wandb.run._backend is not None
    interface = wandb.run._backend.interface
    assert interface is not None
    interface.publish_job_input(
        [_split_on_unesc_dot(tree) for tree in include] if include else [],
        [_split_on_unesc_dot(tree) for tree in exclude] if exclude else [],
        file_path=path,
    )


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

    Raises:
        LaunchError: If there is no active run.
    """
    if wandb.run is None:
        raise LaunchError("This function must be called from a W&B run.")
    assert wandb.run._backend is not None
    interface = wandb.run._backend.interface
    assert interface is not None
    interface.publish_job_input(
        [_split_on_unesc_dot(tree) for tree in include] if include else [],
        [_split_on_unesc_dot(tree) for tree in exclude] if exclude else [],
        run_config=True,
    )


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
