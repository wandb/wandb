import configparser
import os
from typing import Any, Optional

from wandb import util
from wandb.old import core
from wandb import env


class Settings:
    """Global W&B settings stored under $WANDB_CONFIG_DIR/settings."""

    DEFAULT_SECTION = "default"

    _UNSET = object()

    def __init__(
        self, load_settings: bool = True, root_dir: Optional[str] = None
    ) -> None:
        self._global_settings = Settings._settings()
        self._local_settings = Settings._settings()
        self.root_dir = root_dir

        if load_settings:
            self._global_settings.read([Settings._global_path()])
            # Only attempt to read if there is a directory existing
            if os.path.isdir(core.wandb_dir(self.root_dir)):
                self._local_settings.read([Settings._local_path(self.root_dir)])

    def get(self, section: str, key: str, fallback: Any = _UNSET) -> Any:
        # Try the local settings first. If we can't find the key, then try the global settings.
        # If a fallback is provided, return it if we can't find the key in either the local or global
        # settings.
        try:
            return self._local_settings.get(section, key)
        except configparser.NoOptionError:
            try:
                return self._global_settings.get(section, key)
            except configparser.NoOptionError:
                if fallback is not Settings._UNSET:
                    return fallback
                else:
                    raise

    def set(self, section, key, value, globally=False, persist=False) -> None:
        """Persists settings to disk if persist = True"""

        def write_setting(settings, settings_path, persist):
            if not settings.has_section(section):
                Settings._safe_add_section(settings, Settings.DEFAULT_SECTION)
            settings.set(section, key, str(value))
            if persist:
                with open(settings_path, "w+") as f:
                    settings.write(f)

        if globally:
            write_setting(self._global_settings, Settings._global_path(), persist)
        else:
            write_setting(
                self._local_settings, Settings._local_path(self.root_dir), persist
            )

    def clear(self, section, key, globally=False, persist=False) -> None:
        def clear_setting(settings, settings_path, persist):
            settings.remove_option(section, key)
            if persist:
                with open(settings_path, "w+") as f:
                    settings.write(f)

        if globally:
            clear_setting(self._global_settings, Settings._global_path(), persist)
        else:
            clear_setting(
                self._local_settings, Settings._local_path(self.root_dir), persist
            )

    def items(self, section=None):
        section = section if section is not None else Settings.DEFAULT_SECTION

        result = {"section": section}

        try:
            if section in self._global_settings.sections():
                for option in self._global_settings.options(section):
                    result[option] = self._global_settings.get(section, option)
            if section in self._local_settings.sections():
                for option in self._local_settings.options(section):
                    result[option] = self._local_settings.get(section, option)
        except configparser.InterpolationSyntaxError:
            core.termwarn("Unable to parse settings file")

        return result

    @staticmethod
    def _safe_add_section(settings, section):
        if not settings.has_section(section):
            settings.add_section(section)

    @staticmethod
    def _settings(default_settings={}):
        settings = configparser.ConfigParser()
        Settings._safe_add_section(settings, Settings.DEFAULT_SECTION)
        for key, value in default_settings.items():
            settings.set(Settings.DEFAULT_SECTION, key, str(value))
        return settings

    @staticmethod
    def _global_path():
        config_dir = os.environ.get(
            env.CONFIG_DIR, os.path.join(os.path.expanduser("~"), ".config", "wandb")
        )
        util.mkdir_exists_ok(config_dir)
        return os.path.join(config_dir, "settings")

    @staticmethod
    def _local_path(root_dir=None):
        util.mkdir_exists_ok(core.wandb_dir(root_dir))
        return os.path.join(core.wandb_dir(root_dir), "settings")
