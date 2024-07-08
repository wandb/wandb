"""The layer between launch sdk user code and the wandb internal process.

If there is an active run this communication is done through the wandb run's
backend interface.

If there is no active run, the messages are staged on the StagedLaunchInputs
singleton and sent when a run is created.
"""

import os
import pathlib
import shutil
import tempfile
from typing import Any, List, Optional

from pydantic import BaseModel

import wandb
import wandb.data_types
from wandb.sdk.launch.errors import LaunchError
from wandb.sdk.wandb_run import Run

from .files import config_path_is_valid, override_file

PERIOD = "."
BACKSLASH = "\\"
LAUNCH_MANAGED_CONFIGS_DIR = "_wandb_configs"


class ConfigTmpDir:
    """Singleton for managing temporary directories for configuration files.

    Any configuration files designated as inputs to a launch job are copied to
    a temporary directory. This singleton manages the temporary directory and
    provides paths to the configuration files.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = object.__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, "_tmp_dir"):
            self._tmp_dir = tempfile.mkdtemp()
            self._configs_dir = os.path.join(self._tmp_dir, LAUNCH_MANAGED_CONFIGS_DIR)
            os.mkdir(self._configs_dir)

    @property
    def tmp_dir(self):
        return pathlib.Path(self._tmp_dir)

    @property
    def configs_dir(self):
        return pathlib.Path(self._configs_dir)


class JobInputArguments:
    """Arguments for the publish_job_input of Interface."""

    def __init__(
        self,
        include: Optional[List[str]] = None,
        exclude: Optional[List[str]] = None,
        input_schema: Optional[dict] = None,
        file_path: Optional[str] = None,
        run_config: Optional[bool] = None,
    ):
        self.include = include
        self.exclude = exclude
        self.input_schema = input_schema
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
) -> None:
    """Publish a job input to the backend interface of the given run.

    Arguments:
        input (JobInputArguments): The arguments for the job input.
        run (Run): The run to publish the job input to.
    """
    assert run._backend is not None
    assert run._backend.interface is not None
    assert input.run_config is not None

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
        input_schema=input.input_schema,
        run_config=input.run_config,
        file_path=input.file_path or "",
    )


def _replace_refs_and_allofs(schema: dict, defs: dict) -> dict:
    """Recursively fix JSON schemas with common issues.

    1. Replaces any instances of $ref with their associated definition in defs
    2. Removes any "allOf" lists that only have one item, "lifting" the item up
    See test_internal.py for examples
    """
    ret = {}
    if "$ref" in schema:
        # Reference found, replace it with its definition
        def_key = schema["$ref"].split("#/$defs/")[1]
        # Also run recursive replacement in case a ref contains more refs
        return _replace_refs_and_allofs(defs.pop(def_key), defs)
    for key, val in schema.items():
        if isinstance(val, dict):
            # Step into dicts recursively
            new_val = _replace_refs_and_allofs(val, defs)
            ret[key] = new_val
        elif isinstance(val, list):
            # Step into each item in the list
            new_val = []
            for item in val:
                if isinstance(item, dict):
                    new_val.append(_replace_refs_and_allofs(item, defs))
                else:
                    new_val.append(item)
            # Lift up allOf blocks with only one item
            if key == "allOf" and len(new_val) == 1 and isinstance(new_val[0], dict):
                ret.update(new_val[0])
            else:
                ret[key] = new_val
        else:
            # For anything else (str, int, etc) keep it as-is
            ret[key] = val
    return ret


def _convert_model_to_jsonschema(model: BaseModel) -> dict:
    schema = model.model_json_schema()
    defs = schema.pop("$defs")
    if not defs:
        return schema
    schema = _replace_refs_and_allofs(schema, defs)
    # Pull up allOf blocks with only one item
    # schema = _recursive_replace_allof(schema)


def handle_config_file_input(
    path: str,
    include: Optional[List[str]] = None,
    exclude: Optional[List[str]] = None,
    input_schema: Optional[Any] = None,
):
    """Declare an overridable configuration file for a launch job.

    The configuration file is copied to a temporary directory and the path to
    the copy is sent to the backend interface of the active run and used to
    configure the job builder.

    If there is no active run, the configuration file is staged and sent when a
    run is created.
    """
    config_path_is_valid(path)
    override_file(path)
    tmp_dir = ConfigTmpDir()
    dest = os.path.join(tmp_dir.configs_dir, path)
    dest_dir = os.path.dirname(dest)
    if not os.path.exists(dest_dir):
        os.makedirs(dest_dir)
    shutil.copy(
        path,
        dest,
    )
    # Support both input_schema=Schema or input_schema=Schema()
    if isinstance(input_schema, BaseModel) or (
        hasattr(input_schema, "model_json_schema")
        and callable(input_schema.model_json_schema)
    ):
        input_schema = _convert_model_to_jsonschema(input_schema)
    arguments = JobInputArguments(
        include=include,
        exclude=exclude,
        input_schema=input_schema,
        file_path=path,
        run_config=False,
    )
    if wandb.run is not None:
        _publish_job_input(arguments, wandb.run)
    else:
        staged_inputs = StagedLaunchInputs()
        staged_inputs.add_staged_input(arguments)


def handle_run_config_input(
    include: Optional[List[str]] = None,
    exclude: Optional[List[str]] = None,
    input_schema: Optional[dict | BaseModel] = None,
):
    """Declare wandb.config as an overridable configuration for a launch job.

    The include and exclude paths are sent to the backend interface of the
    active run and used to configure the job builder.

    If there is no active run, the include and exclude paths are staged and sent
    when a run is created.
    """
    if isinstance(input_schema, BaseModel):
        input_schema = _convert_model_to_jsonschema(input_schema)
    arguments = JobInputArguments(
        include=include,
        exclude=exclude,
        input_schema=input_schema,
        run_config=True,
        file_path=None,
    )
    if wandb.run is not None:
        _publish_job_input(arguments, wandb.run)
    else:
        stage_inputs = StagedLaunchInputs()
        stage_inputs.add_staged_input(arguments)


def _split_on_unesc_dot(path: str) -> List[str]:
    r"""Split a string on unescaped dots.

    Arguments:
        path (str): The string to split.

    Raises:
        ValueError: If the path has a trailing escape character.

    Returns:
        List[str]: The split string.
    """
    parts = []
    part = ""
    i = 0
    while i < len(path):
        if path[i] == BACKSLASH:
            if i == len(path) - 1:
                raise LaunchError(
                    f"Invalid config path {path}: trailing {BACKSLASH}.",
                )
            if path[i + 1] == PERIOD:
                part += PERIOD
                i += 2
        elif path[i] == PERIOD:
            parts.append(part)
            part = ""
            i += 1
        else:
            part += path[i]
            i += 1
    if part:
        parts.append(part)
    return parts
