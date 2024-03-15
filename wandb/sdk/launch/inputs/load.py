import json
import os
from typing import Any

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
