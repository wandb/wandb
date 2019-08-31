import os
from six.moves import configparser

import wandb.util as util
from wandb import core, env, wandb_dir


class Settings(object):
    """Global W&B settings stored under $WANDB_CONFIG_DIR/settings.
    """

    DEFAULT_SECTION = "default"

    def __init__(self, load_settings=True):
        config_dir = os.environ.get(env.CONFIG_DIR, os.path.join(os.path.expanduser("~"), ".config", "wandb"))

        # Ensure the config directory and settings file both exist.
        util.mkdir_exists_ok(config_dir)
        util.mkdir_exists_ok(wandb_dir())

        self._global_settings_path = os.path.join(config_dir, 'settings')
        self._global_settings = Settings._settings_wth_defaults({})

        self._local_settings_path = os.path.join(wandb_dir(), 'settings')
        self._local_settings = Settings._settings_wth_defaults({})

        if load_settings:
            self._global_settings.read([self._global_settings_path])
            self._local_settings.read([self._local_settings_path])

    def get(self, section, key, fallback=configparser._UNSET):
        # Try the local settings first. If we can't find the key, then try the global settings.
        # If a fallback is provided, return it if we can't find the key in either the local or global
        # settings.
        try:
            return self._local_settings.get(section, key)
        except configparser.NoOptionError:
            return self._global_settings.get(section, key, fallback=fallback)

    def set(self, section, key, value, globally=False):
        def write_setting(settings, settings_path):
            if not settings.has_section(section):
                settings.add_section(section)
            settings.set(section, key, str(value))
            with open(settings_path, "w+") as f:
                settings.write(f)

        if globally:
            write_setting(self._global_settings, self._global_settings_path)
        else:
            write_setting(self._local_settings, self._local_settings_path)

    def clear(self, section, key, globally=False):
        def clear_setting(settings, settings_path):
            settings.remove_option(section, key)
            with open(settings_path, "w+") as f:
                settings.write(f)

        if globally:
            clear_setting(self._global_settings, self._global_settings_path)
        else:
            clear_setting(self._local_settings, self._local_settings_path)

    def items(self, section=None):
        section = section if section is not None else Settings.DEFAULT_SECTION

        result = {'section': section}

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
    def _settings_wth_defaults(default_settings):
        config = configparser.ConfigParser()
        config.add_section(Settings.DEFAULT_SECTION)
        for key, value in default_settings.items():
            config.set(Settings.DEFAULT_SECTION, key, str(value))
        return config
