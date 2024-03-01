"""Functions for declaring and patching config files as part of a run template."""

import json
import os
from typing import Any, Optional

import yaml

FILE_OVERRIDE_ENV_VAR = "WANDB_LAUNCH_FILE_OVERRIDES"


class FileOverrides:
    """Singleton that read file overrides json from environment variables."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = object.__new__(cls)
            cls._instance.overrides = {}
        return cls._instance

    def load(self) -> Any:
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
                self.overrides = json.loads(overrides)
            except json.JSONDecodeError:
                raise ValueError(f"Invalid JSON in {FILE_OVERRIDE_ENV_VAR}")


class ConfigFile:
    """A class for declaring a config file as part of a run template."""

    def __init__(
        self,
        path: str,
        include: Optional[list[str]] = None,
        ignore: Optional[list[str]] = None,
    ):
        """Initialize a ConfigFile object.

        When this object is initialized, it checks WANDB_LAUNCH_OVERRIDES for any
        overrides to the config file. If an override is found, the config file is
        patched with the override.
        """
        self.abspath = os.path.dirname(os.path.abspath(path))
        self.relpath = os.path.dirname(path)
        self.relpath = os.path.relpath(self.abspath, os.getcwd())
        self.filename = os.path.basename(path)
        self.include = include
        self.ignore = ignore
        self._ensure_override()  # Ensure that the config file is patched with any overrides.

    def full_relpath(self) -> str:
        return os.path.join(self.relpath, self.filename)

    def _ensure_override(self) -> None:
        """Check WANDB_LAUNCH_OVERRIDES for any overrides to the config file.

        If an override is found, the config file is patched with the override.

        Returns:
            bool: True if an override was found, False otherwise.
        """
        overrides = FileOverrides().overrides
        file_overrides = overrides.get(self.full_relpath())
        if file_overrides is not None:
            self.patch(file_overrides)

    def patch(self, overrides: dict[str, Any]) -> None:
        """Patch the config file with overrides.

        Args:
            overrides (dict[str, Any]): The overrides to apply to the config file.
        """
        # config = _read_config_file(os.path.join(self.abspath, self.filename))
        # config.update(overrides)
        _write_config_file(os.path.join(self.abspath, self.filename), overrides)


def _write_config_file(path: str, config: Any) -> None:
    """Write a config file to disk.

    Args:
        path (str): The path to the config file.
        config (Any): The contents of the config file as a Python object.

    Raises:
        ValueError: If the file extension is not supported.
    """
    _, ext = os.path.splitext(path)
    if ext == ".json":
        with open(path, "w") as f:
            json.dump(config, f, indent=2)
    elif ext in [".yaml", ".yml"]:
        with open(path, "w") as f:
            yaml.safe_dump(config, f)
    else:
        raise ValueError(f"Unsupported file extension: {ext}")


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
        raise ValueError(f"Unsupported file extension: {ext}")
