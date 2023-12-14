import configparser
import getpass
import os
import tempfile
from typing import Any, Optional

from wandb import env
from wandb.old import core
from wandb.sdk.lib import filesystem
from wandb.sdk.lib.runid import generate_id


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
            global_path = Settings._global_path()
            if global_path is not None:
                self._global_settings.read([global_path])
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
            global_path = Settings._global_path()
            if global_path is not None:
                write_setting(self._global_settings, global_path, persist)
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
            global_path = Settings._global_path()
            if global_path is not None:
                clear_setting(self._global_settings, global_path, persist)
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
    def _global_path() -> Optional[str]:
        def try_create_dir(path) -> bool:
            try:
                os.makedirs(path, exist_ok=True)
                if os.access(path, os.W_OK):
                    return True
            except OSError:
                pass
            return False

        def get_username() -> str:
            try:
                return getpass.getuser()
            except (ImportError, KeyError):
                return generate_id()

        try:
            home_config_dir = os.path.join(os.path.expanduser("~"), ".config", "wandb")

            if not try_create_dir(home_config_dir):
                temp_config_dir = os.path.join(
                    tempfile.gettempdir(), ".config", "wandb"
                )

                if not try_create_dir(temp_config_dir):
                    username = get_username()
                    config_dir = os.path.join(
                        tempfile.gettempdir(), username, ".config", "wandb"
                    )
                    try_create_dir(config_dir)
                else:
                    config_dir = temp_config_dir
            else:
                config_dir = home_config_dir

            config_dir = os.environ.get(env.CONFIG_DIR, config_dir)
            return os.path.join(config_dir, "settings")
        except Exception:
            return None

    @staticmethod
    def _local_path(root_dir=None):
        filesystem.mkdir_exists_ok(core.wandb_dir(root_dir))
        return os.path.join(core.wandb_dir(root_dir), "settings")
