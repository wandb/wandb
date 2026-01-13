"""Reading and writing W&B settings files.

There is usually a "global" settings file at ~/.config/wandb/settings.
A "local" settings file, also referred to as "workspace settings", is created
by the `wandb init` CLI command at ./wandb/settings. Any settings defined in
the local file override settings in the global file.

These settings files are generally updated by CLI commands like `wandb online`,
`wandb offline` and `wandb login`, but it is possible to modify them manually.
The most common settings found in these files are `base_url` (the W&B server
URL if not using SaaS) and `mode` (online or offline).
"""

from __future__ import annotations

import configparser
import logging
import pathlib

from wandb.errors import Error, term

# The only section name we recognize in all settings files.
_SECTION_NAME = "default"


_logger = logging.getLogger(__name__)


class SaveSettingsError(Error):
    """Could not update one or more settings files.

    The __str__ representation is written to be printed to a terminal.
    """


class SettingsFiles:
    """System settings as determined by the settings files."""

    def __init__(
        self,
        *,
        global_settings: pathlib.Path | None,
        local_settings: pathlib.Path,
    ) -> None:
        """Open system settings file(s) for reading and writing.

        If the files don't exist, they are treated as empty.
        If there are problems reading the files, the files are treated as empty
        and the problems are logged and printed to the terminal.

        Args:
            global_settings: The global settings file path. If None, local
                settings are used for everything.
            local_settings: The local settings file path.
        """
        self._local_modified = False
        self._global_modified = False

        self._global_path = global_settings
        self._local_path = local_settings
        self._sources: list[pathlib.Path] = []

        if self._global_path and (settings := _try_read(self._global_path)):
            self._sources.append(self._global_path)
            self._global_settings = settings
        else:
            self._global_settings = {}

        if settings := _try_read(self._local_path):
            self._sources.append(self._local_path)
            self._local_settings = settings
        else:
            self._local_settings = {}

    @property
    def sources(self) -> list[pathlib.Path]:
        """Returns the list of file paths in which settings were found.

        This does not include files that were empty or did not exist.
        """
        return self._sources

    def save(self) -> None:
        """Write changes to settings files.

        This is a no-op if neither set() nor clear() were ever called,
        or if they made no changes.

        Raises:
            SaveSettingsError: If failed to write one or more files.
        """
        if self._local_modified:
            _write(self._local_path, self._local_settings)

        if self._global_path and self._global_modified:
            _write(self._global_path, self._global_settings)

    def all(self) -> dict[str, str]:
        """Returns settings as a dictionary."""
        settings = self._global_settings.copy()
        settings.update(self._local_settings)
        return settings

    def set(self, key: str, value: str, *, globally: bool = False) -> None:
        """Set a new value for a setting.

        Args:
            key: The name of the setting.
            value: The setting's new value.
            globally: If false or if there's no global settings file,
                update only the local settings file.
                Otherwise, remove this setting from local settings and update
                global settings.
        """
        if not globally or not self._global_path:
            old_value = self._local_settings.get(key)
            self._local_settings[key] = value
            if old_value != value:
                self._local_modified = True

        else:
            old_value = self._local_settings.pop(key, None)
            if old_value is not None:
                self._local_modified = True

            old_value = self._global_settings.get(key)
            self._global_settings[key] = value
            if old_value != value:
                self._global_modified = True

    def clear(self, key: str, *, globally: bool = False) -> None:
        """Clear a setting.

        Args:
            key: The name of the setting.
            globally: If false, update only the local settings file.
                If true, update both local and global settings.
        """
        old_value = self._local_settings.pop(key, None)
        if old_value is not None:
            self._local_modified = True

        if globally:
            old_value = self._global_settings.pop(key, None)
            if old_value is not None:
                self._global_modified = True


def _try_read(path: pathlib.Path) -> dict[str, str]:
    """Try to read the settings file at the given path.

    Returns an empty dictionary if the file doesn't exist or if there's
    any problem reading the file. In the latter case, prints a warning as well.
    """
    try:
        # The exists() check can hit a permission error.
        if not path.exists():
            return {}
    except OSError as e:
        _logger.exception(f"Error reading settings at {path}")
        term.termwarn(f"Error reading settings at {path}: {e}", repeat=False)

    parser = configparser.ConfigParser()

    try:
        parser.read(path)
    except (OSError, configparser.Error) as e:
        _logger.exception(f"Error reading settings at {path}")
        term.termwarn(f"Error reading settings at {path}: {e}", repeat=False)
        return {}

    try:
        return dict(parser.items(section=_SECTION_NAME))
    except configparser.NoSectionError:
        return {}


def _write(path: pathlib.Path, settings: dict[str, str]) -> None:
    """Try to update the settings file at the path.

    Raises:
        SaveSettingsError: If unable to remove or update the file.
    """
    parser = configparser.ConfigParser()
    parser.add_section(_SECTION_NAME)
    for key, value in settings.items():
        parser.set(_SECTION_NAME, key, value)

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w") as f:
            parser.write(f)
    except (OSError, configparser.Error) as e:
        raise SaveSettingsError(f"Error updating settings at {path}: {e}") from e

    term.termlog(f"Updated settings file {path}")
