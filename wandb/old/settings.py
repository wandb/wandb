import configparser
import getpass
import os
import tempfile
from typing import Any, Optional

from wandb import env
from wandb.old import core
from wandb.sdk.lib import filesystem


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

    def _persist_settings(self, settings, settings_path) -> None:
        # write a temp file and then move it to the settings path
        target_dir = os.path.dirname(settings_path)
        with tempfile.NamedTemporaryFile(
            "w+", suffix=".tmp", delete=False, dir=target_dir
        ) as fp:
            path = os.path.abspath(fp.name)
            with open(path, "w+") as f:
                settings.write(f)
        try:
            os.replace(path, settings_path)
        except AttributeError:
            os.rename(path, settings_path)

    def set(self, section, key, value, globally=False, persist=False) -> None:
        """Persist settings to disk if persist = True"""

        def write_setting(settings, settings_path, persist):
            if not settings.has_section(section):
                Settings._safe_add_section(settings, Settings.DEFAULT_SECTION)
            settings.set(section, key, str(value))

            if persist:
                self._persist_settings(settings, settings_path)

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
                self._persist_settings(settings, settings_path)

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
        default_config_dir = os.path.join(os.path.expanduser("~"), ".config", "wandb")
        # if not writable, fall back to a temp directory
        if not os.access(default_config_dir, os.W_OK):
            default_config_dir = os.path.join(tempfile.gettempdir(), ".config", "wandb")
        # if not writable (if tempdir is shared, for example), try creating a subdir
        if not os.access(default_config_dir, os.W_OK):
            username = getpass.getuser()
            default_config_dir = os.path.join(
                tempfile.gettempdir(), username, ".config", "wandb"
            )

        config_dir = os.environ.get(env.CONFIG_DIR, default_config_dir)
        os.makedirs(config_dir, exist_ok=True)
        return os.path.join(config_dir, "settings")

    @staticmethod
    def _local_path(root_dir=None):
        filesystem.mkdir_exists_ok(core.wandb_dir(root_dir))
        return os.path.join(core.wandb_dir(root_dir), "settings")
