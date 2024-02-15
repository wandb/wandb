"""Functions for managing config files as run template parameters."""

import os


class ConfigFile:
    """Wrapper for a config file that can be used as a run template parameter.

    In the context of a run, this class is used both to register a config file
    as a run template parameter and to apply override files if they are detected.
    """

    def __init__(self, path, alias=None, raw=False):
        self.path = path
        self.alias = alias
        self.raw = raw

        override = os.environ.get(f"WANDB_CONFIG_FILE_{self.alias}")
        # Overwrite the contents of the file with the override.
        if override:
            # TODO: Overwrite the values in memory.
            pass

    def get_schema(self):
        """Extract a schema from the config file."""
        assert not self.raw, "Raw config files do not have a schema."
        # Load file, get schema.
