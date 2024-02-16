"""Functions for declaring and patching config files as part of a run template."""

import json
import os
from typing import Any, Optional

import yaml


class ConfigFile:
    """A class for declaring a config file as part of a run template."""

    def __init__(
        self,
        path: str,
        alias: Optional[str] = None,
    ):
        """Initialize a ConfigFile object.

        When this object is initialized, it checks WANDB_LAUNCH_OVERRIDES for any
        overrides to the config file. If an override is found, the config file is
        patched with the override.
        """
        self.path = path
        self.basename = os.path.basename(path)
        self.name = alias or self.basename
        _, ext = os.path.splitext(path)
        if ext not in [".json", ".yaml", ".yml"]:
            raise ValueError(f"Unsupported config file extensiona: {ext}")
        self._ensure_override()  # Ensure that the config file is patched with any overrides.

    def _ensure_override(self) -> None:
        """Check WANDB_LAUNCH_OVERRIDES for any overrides to the config file.

        If an override is found, the config file is patched with the override.

        Returns:
            bool: True if an override was found, False otherwise.
        """
        overrides = _load_overrides(self.name)
        if overrides is not None:
            _write_config_file(self.path, overrides)


def _load_overrides(name: str) -> Any:
    """Load overrides from an environment variable."""
    if f"WANDB_OVERRIDE__{name}" in os.environ:
        overrides = os.environ[f"WANDB_OVERRIDE__{name}"]
    elif f"WANDB_OVERRIDE__{name}_0" in os.environ:
        overrides = ""
        idx = 0
        while f"WANDB_OVERRIDE__{name}_{idx}" in os.environ:
            overrides += os.environ[f"WANDB_OVERRIDE__{name}_{idx}"]
            idx += 1
    else:
        return
    try:
        return json.loads(overrides)
    except json.JSONDecodeError:
        raise ValueError(f"Invalid JSON in WANDB_OVERRIDE__{name}")


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
