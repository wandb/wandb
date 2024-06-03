import json
import os
from typing import Any, Dict

import yaml

from ..errors import LaunchError

FILE_OVERRIDE_ENV_VAR = "WANDB_LAUNCH_FILE_OVERRIDES"


class FileOverrides:
    """Singleton that read file overrides json from environment variables."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = object.__new__(cls)
            cls._instance.overrides = {}
            cls._instance.load()
        return cls._instance

    def load(self) -> None:
        """Load overrides from an environment variable."""
        overrides = os.environ.get(FILE_OVERRIDE_ENV_VAR)
        if overrides is None:
            if f"{FILE_OVERRIDE_ENV_VAR}_0" in os.environ:
                overrides = ""
                idx = 0
                while f"{FILE_OVERRIDE_ENV_VAR}_{idx}" in os.environ:
                    overrides += os.environ[f"{FILE_OVERRIDE_ENV_VAR}_{idx}"]
                    idx += 1
        if overrides:
            try:
                contents = json.loads(overrides)
                if not isinstance(contents, dict):
                    raise LaunchError(f"Invalid JSON in {FILE_OVERRIDE_ENV_VAR}")
                self.overrides = contents
            except json.JSONDecodeError:
                raise LaunchError(f"Invalid JSON in {FILE_OVERRIDE_ENV_VAR}")


def config_path_is_valid(path: str) -> None:
    """Validate a config file path.

    This function checks if a given config file path is valid. A valid path
    should meet the following criteria:

    - The path must be expressed as a relative path without any upwards path
      traversal, e.g. `../config.json`.
    - The file specified by the path must exist.
    - The file must have a supported extension (`.json`, `.yaml`, or `.yml`).

    Args:
        path (str): The path to validate.

    Raises:
        LaunchError: If the path is not valid.
    """
    if os.path.isabs(path):
        raise LaunchError(
            f"Invalid config path: {path}. Please provide a relative path."
        )
    if ".." in path:
        raise LaunchError(
            f"Invalid config path: {path}. Please provide a relative path "
            "without any upward path traversal, e.g. `../config.json`."
        )
    path = os.path.normpath(path)
    if not os.path.exists(path):
        raise LaunchError(f"Invalid config path: {path}. File does not exist.")
    if not any(path.endswith(ext) for ext in [".json", ".yaml", ".yml"]):
        raise LaunchError(
            f"Invalid config path: {path}. Only JSON and YAML files are supported."
        )


def override_file(path: str) -> None:
    """Check for file overrides in the environment and apply them if found."""
    file_overrides = FileOverrides()
    if path in file_overrides.overrides:
        overrides = file_overrides.overrides.get(path)
        if overrides is not None:
            config = _read_config_file(path)
            _update_dict(config, overrides)
            _write_config_file(path, config)


def _write_config_file(path: str, config: Any) -> None:
    """Write a config file to disk.

    Args:
        path (str): The path to the config file.
        config (Any): The contents of the config file as a Python object.

    Raises:
        LaunchError: If the file extension is not supported.
    """
    _, ext = os.path.splitext(path)
    if ext == ".json":
        with open(path, "w") as f:
            json.dump(config, f, indent=2)
    elif ext in [".yaml", ".yml"]:
        with open(path, "w") as f:
            yaml.safe_dump(config, f)
    else:
        raise LaunchError(f"Unsupported file extension: {ext}")


def _read_config_file(path: str) -> Any:
    """Read a config file from disk.

    Args:
        path (str): The path to the config file.

    Returns:
        Any: The contents of the config file as a Python object.
    """
    _, ext = os.path.splitext(path)
    if ext == ".json":
        with open(
            path,
        ) as f:
            return json.load(f)
    elif ext in [".yaml", ".yml"]:
        with open(
            path,
        ) as f:
            return yaml.safe_load(f)
    else:
        raise LaunchError(f"Unsupported file extension: {ext}")


def _update_dict(target: Dict, source: Dict) -> None:
    """Update a dictionary with the contents of another dictionary.

    Args:
        target (Dict): The dictionary to update.
        source (Dict): The dictionary to update from.
    """
    for key, value in source.items():
        if isinstance(value, dict):
            if key not in target:
                target[key] = {}
            _update_dict(target[key], value)
        else:
            target[key] = value
