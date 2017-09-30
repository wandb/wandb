import yaml
import os
import sys
import logging
from .api import Error

logger = logging.getLogger(__name__)


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

    def __init__(self, config_paths=[], wandb_dir=None, run_dir=None, persist_callback=None):
        object.__setattr__(self, '_wandb_dir', wandb_dir)
        object.__setattr__(self, '_run_dir', run_dir)

        # TODO: Replace this with an event system.
        object.__setattr__(self, '_persist_callback', persist_callback)

        object.__setattr__(self, '_items', {})
        object.__setattr__(self, '_descriptions', {})

        self._load_defaults()
        for conf_path in config_paths:
            self._load_file(conf_path)
        self._persist()

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
            raise Error('Couldn\'t read config file: %s' % conf_path)
        try:
            loaded = yaml.load(conf_file)
        except yaml.parser.ParserError:
            raise Error('Invalid YAML in config-defaults.yaml')
        if subkey:
            try:
                loaded = loaded[subkey]
            except KeyError:
                raise Error('Asked for %s but %s not present in %s' % (
                    path, subkey, conf_path))
        self._update_from_dict(
            loaded, error_prefix='In config %s, ' % path)

    def _update_from_dict(self, items, error_prefix=''):
        if not isinstance(items, dict):
            raise Error('%sExpected dict but received %s' %
                        (error_prefix, items))
        for key, val in items.items():
            if key == 'wandb_version':
                continue
            self._set_key(key, val, error_prefix=error_prefix)

    def _set_key(self, key, val, error_prefix=''):
        if isinstance(val, dict):
            if 'value' not in val:
                raise Error('%svalue of %s is dict, but does not contain "value" key' % (
                    error_prefix, key))
            self._items[key] = val['value']
            if 'desc' in val:
                self._descriptions[key] = val['desc']
        else:
            self._items[key] = val

    def keys(self):
        """All keys in the current configuration"""
        return self._items.keys()

    def desc(self, key):
        """The description of a given key"""
        return self._descriptions.get(key)

    def load_json(self, json):
        """Loads existing config from JSON"""
        for key in json:
            self._items[key] = json[key].get('value')
            self._descriptions[key] = json[key].get('desc')

    def _persist(self):
        """Stores the current configuration for pushing to W&B"""
        if not self._run_dir or not os.path.isdir(self._run_dir):
            # In dryrun mode, without wandb run, we don't
            # save config  on initial load, because the run directory
            # may not be created yet (because we don't know if we're
            # being used in a run context, or as an API).
            # TODO: Defer saving somehow, maybe via an events system
            return
        path = os.path.join(self._run_dir, 'config.yaml')
        with open(path, "w") as conf_file:
            conf_file.write(str(self))

        # TODO: Replace with events
        if self._persist_callback:
            self._persist_callback()

    def get(self, *args):
        return self._items.get(*args)

    def __getitem__(self, key):
        return self._items[key]

    def __setitem__(self, key, val):
        self._set_key(key, val)
        self._persist()

    __setattr__ = __setitem__

    def __getattr__(self, key):
        return self.__getitem__(key)

    def update(self, params):
        if not isinstance(params, dict):
            try:
                # for tensorflow flags
                if "__flags" in dir(params):
                    if not params.__dict__['__parsed']:
                        params._parse_flags()
                    params = params.__dict__['__flags']
                else:
                    params = vars(params)
            except TypeError:
                raise TypeError(
                    "config must be a dict or have a __dict__ attribute.")
        self._update_from_dict(params)
        self._persist()

    def as_dict(self):
        defaults = {}
        for key, val in self._items.items():
            defaults[key] = {'value': val,
                             'desc': self._descriptions.get(key)}
        return defaults

    def __str__(self):
        s = "wandb_version: 1\n\n"
        s += yaml.dump(self.as_dict(), default_flow_style=False)
        return s
