"""Communication between launch sdk user code and the wandb internal process.

If there is an active run this communication is done through the wandb run's
backend interface.

If there is no active run, the messages are staged on the StagedLaunchInputs
singleton and sent when a run is created.
"""

import os
import pathlib
import shutil
import tempfile
from typing import List, Optional

import wandb
import wandb.data_types
from wandb.sdk.wandb_run import Run

from .files import config_path_is_valid, override_file


class ConfigTmpDir:
    """Singleton for managing temporary directories for configuration files."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = object.__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, "_tmp_dir"):
            self._tmp_dir = tempfile.mkdtemp()
            self._configs_dir = os.path.join(self._tmp_dir, "configs")
            os.mkdir(self._configs_dir)

    @property
    def tmp_dir(self):
        return pathlib.Path(self._tmp_dir)

    @property
    def configs_dir(self):
        return pathlib.Path(self._configs_dir)


class JobInputArguments:
    """Arguments for the publish_job_input method."""

    def __init__(
        self,
        include: Optional[List[str]] = None,
        exclude: Optional[List[str]] = None,
        file_path: Optional[str] = None,
        run_config: Optional[bool] = None,
    ):
        self.include = include
        self.exclude = exclude
        self.file_path = file_path
        self.run_config = run_config


class StagedLaunchInputs:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = object.__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if not hasattr(self, "_staged_inputs"):
            self._staged_inputs: List[JobInputArguments] = []

    def add_staged_input(
        self,
        input_arguments: JobInputArguments,
    ):
        self._staged_inputs.append(input_arguments)

    def apply(self, run: Run):
        """Apply the staged inputs to the given run."""
        for input in self._staged_inputs:
            _publish_job_input(input, run)


def _publish_job_input(
    input: JobInputArguments,
    run: Run,
):
    """Publish a job input to the backend interface of the given run."""
    assert run._backend is not None
    assert run._backend.interface is not None
    interface = run._backend.interface
    if input.file_path:
        config_dir = ConfigTmpDir()
        dest = os.path.join(config_dir.configs_dir, input.file_path)
        run.save(dest, base_path=config_dir.tmp_dir)
    interface.publish_job_input(
        include_paths=[_split_on_unesc_dot(path) for path in input.include]
        if input.include
        else [],
        exclude_paths=[_split_on_unesc_dot(path) for path in input.exclude]
        if input.exclude
        else [],
        run_config=input.run_config,
        file_path=input.file_path,
    )


def handle_config_file_input(
    path: str,
    include: Optional[List[str]] = None,
    exclude: Optional[List[str]] = None,
):
    """Declare an overridable configuration file for a launch job."""
    config_path_is_valid(path)
    override_file(path)
    tmp_dir = ConfigTmpDir()
    dest = os.path.join(tmp_dir.configs_dir, path)
    shutil.copy(path, dest)
    staged_inputs = StagedLaunchInputs()
    arguments = JobInputArguments(
        include=include,
        exclude=exclude,
        file_path=path,
        run_config=False,
    )
    if wandb.run is not None:
        _publish_job_input(arguments, wandb.run)
    else:
        staged_inputs.add_staged_input(arguments)


def handle_run_config_input(
    include: Optional[List[str]] = None, exclude: Optional[List[str]] = None
):
    """Declare wandb.config as an overridable configuration for a launch job."""
    staged_inputs = StagedLaunchInputs()
    arguments = JobInputArguments(
        include=include,
        exclude=exclude,
        run_config=True,
    )
    if wandb.run is not None:
        _publish_job_input(arguments, wandb.run)
    else:
        staged_inputs.add_staged_input(arguments)


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
