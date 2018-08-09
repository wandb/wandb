from collections import OrderedDict
import inspect
import logging
import os
import sys
import types
import yaml

import wandb

FNAME = 'config.yaml'

logger = logging.getLogger(__name__)


class ConfigError(wandb.Error):
    pass


def boolify(s):
    if s.lower() == 'none':
        return None
    if s.lower() == 'true':
        return True
    if s.lower() == 'false':
        return False
    raise ValueError("Not a boolean")


class Config(object):
    """Creates a W&B config object."""

    def __init__(self, config_paths=[], wandb_dir=None, run_dir=None):
        object.__setattr__(self, '_wandb_dir', wandb_dir)

        # OrderedDict to make writing unit tests easier. (predictable order for
        # .key())
        object.__setattr__(self, '_items', OrderedDict())
        object.__setattr__(self, '_descriptions', {})

        self._load_defaults()
        for conf_path in config_paths:
            self._load_file(conf_path)

        # Do this after defaults because it triggers loading of pre-existing
        # config.yaml (if it exists)
        self.set_run_dir(run_dir)

        self.persist()

    @classmethod
    def from_environment_or_defaults(cls):
        conf_paths = os.environ.get('WANDB_CONFIG_PATHS', [])
        if conf_paths:
            conf_paths = conf_paths.split(',')
        return Config(config_paths=conf_paths, wandb_dir=wandb.wandb_dir())

    def _load_defaults(self):
        if not self._wandb_dir:
            logger.debug('wandb dir not provided, skipping defaults')
            return
        defaults_path = os.path.join('config-defaults.yaml')
        if not os.path.exists(defaults_path):
            logger.debug('no defaults not found in %s' % defaults_path)
            return
        self._load_file(defaults_path)

    def _load_file(self, path):
        subkey = None
        if '::' in path:
            conf_path, subkey = path.split('::', 1)
        else:
            conf_path = path
        try:
            conf_file = open(conf_path)
        except (OSError, IOError):
            raise ConfigError('Couldn\'t read config file: %s' % conf_path)
        try:
            loaded = yaml.load(conf_file)
        except yaml.parser.ParserError:
            raise ConfigError('Invalid YAML in config-defaults.yaml')
        if subkey:
            try:
                loaded = loaded[subkey]
            except KeyError:
                raise ConfigError('Asked for %s but %s not present in %s' % (
                    path, subkey, conf_path))
        for key, val in loaded.items():
            if key == 'wandb_version':
                continue
            if isinstance(val, dict):
                if 'value' not in val:
                    raise ConfigError('In config %s value of %s is dict, but does not contain "value" key' % (
                        path, key))
                self._items[key] = val['value']
                if 'desc' in val:
                    self._descriptions[key] = val['desc']
            else:
                self._items[key] = val

    def _load_values(self):
        """Load config.yaml from the run directory if available."""
        path = self._config_path()
        if path is not None and os.path.isfile(path):
            self._load_file(path)

    def _config_path(self):
        if self._run_dir and os.path.isdir(self._run_dir):
            return os.path.join(self._run_dir, FNAME)
        return None

    def keys(self):
        """All keys in the current configuration"""
        return self._items.keys()

    def desc(self, key):
        """The description of a given key"""
        return self._descriptions.get(key)

    def load_json(self, json):
        """Loads existing config from JSON"""
        for key in json:
            if key == "wandb_version":
                continue
            self._items[key] = json[key].get('value')
            self._descriptions[key] = json[key].get('desc')

    def set_run_dir(self, run_dir):
        """Set the run directory to which this Config should be persisted.

        Changes to this Config won't be written anywhere unless the run directory
        is set.
        """
        object.__setattr__(self, '_run_dir', run_dir)
        self._load_values()

    def persist(self):
        """Stores the current configuration for pushing to W&B"""
        # In dryrun mode, without wandb run, we don't
        # save config  on initial load, because the run directory
        # may not be created yet (because we don't know if we're
        # being used in a run context, or as an API).
        # TODO: Defer saving somehow, maybe via an events system
        path = self._config_path()
        if path is None:
            return
        with open(path, "w") as conf_file:
            conf_file.write(str(self))

    def get(self, *args):
        return self._items.get(*args)

    def __getitem__(self, key):
        return self._items[key]

    def __setitem__(self, key, val):
        key = self._sanitize(key, val)
        self._items[key] = val
        self.persist()

    __setattr__ = __setitem__

    def __getattr__(self, key):
        return self.__getitem__(key)

    def _sanitize(self, key, val, allow_val_change=False):
        # We always normalize keys by stripping '-'
        key = key.strip('-')
        if not allow_val_change:
            if key in self._items and val != self._items[key]:
                raise ConfigError('Attempted to change value of key "%s" from %s to %s\nIf you really want to do this, pass allow_val_change=True to config.update()' % (
                    key, self._items[key], val))
        return key

    def update(self, params, allow_val_change=False):
        if not isinstance(params, dict):
            # Handle some cases where params is not a dictionary
            # by trying to convert it into a dictionary
            meta = inspect.getmodule(params)
            if meta:
                is_tf_flags_module = isinstance(params, types.ModuleType) and meta.__name__ == 'tensorflow.python.platform.flags'
                if is_tf_flags_module or meta.__name__ == 'absl.flags':
                    params = params.FLAGS
                    meta = inspect.getmodule(params)

            # newer tensorflow flags (post 1.4) uses absl.flags
            if meta and meta.__name__ == "absl.flags._flagvalues":
                params = {name: params[name].value for name in dir(params)}
            elif "__flags" in vars(params):
                # for older tensorflow flags (pre 1.4)
                if not '__parsed' in vars(params):
                    params._parse_flags()
                params = vars(params)['__flags']
            elif not hasattr(params, '__dict__'):
                raise TypeError(
                    "config must be a dict or have a __dict__ attribute.")
            else:
                # params is a Namespace object (argparse)
                # or something else
                params = vars(params)

        if not isinstance(params, dict):
            raise ConfigError('Expected dict but received %s' % params)
        for key, val in params.items():
            key = self._sanitize(key, val, allow_val_change=allow_val_change)
            self._items[key] = val
        self.persist()

    def as_dict(self):
        defaults = {}
        for key, val in self._items.items():
            defaults[key] = {'value': val,
                             'desc': self._descriptions.get(key)}
        return defaults

    def __str__(self):
        s = "wandb_version: 1"
        as_dict = self.as_dict()
        if as_dict:  # adding an empty dictionary here causes a parse error
            s += '\n\n' + yaml.dump(as_dict, default_flow_style=False)
        return s
