"""
settings.
"""

import collections
import logging
import configparser
import platform
from typing import Optional, Union, List, Dict  # noqa: F401 pylint: disable=unused-import
import copy

import six

logger = logging.getLogger("wandb")

source = ("org", "entity", "project", "sysdir", "dir", "env", "setup",
          "settings", "args")

Field = collections.namedtuple('TypedField', ['type', 'choices'])

defaults = dict(
    base_url="https://api.wandb.ai",
    show_warnings=2,
    summary_warnings=5,
    _mode=Field(str, (
        'auto',
        'noop',
        'online',
        'offline',
        'dryrun',
        'run',
    )),
    _problem=Field(str, (
        'fatal',
        'warn',
        'silent',
    )),
    console='auto',
    _console=Field(str, (
        'auto',
        'redirect',
        'off',
        'mock',
        'file',
        'iowrap',
    )),
)

# env mapping?
env_prefix = "WANDB_"
env_settings = dict(
    entity=None,
    project=None,
    base_url=None,
    mode=None,
    group="WANDB_RUN_GROUP",
    job_type=None,
    problem=None,
    console=None,
    run_name="WANDB_NAME",
    run_notes="WANDB_NOTES",
    run_tags="WANDB_TAGS",
)

env_convert = dict(run_tags=lambda s: s.split(','), )


def _build_inverse_map(prefix, d):
    inv_map = dict()
    for k, v in six.iteritems(d):
        v = v or prefix + k.upper()
        inv_map[v] = k
    return inv_map


def _get_python_type():
    try:
        if 'terminal' in get_ipython().__module__:
            return 'ipython'
        else:
            return 'jupyter'
    except (NameError, AttributeError):
        return "python"


class CantTouchThis(type):
    def __setattr__(cls, attr, value):
        raise Exception("NO!")


class Settings(six.with_metaclass(CantTouchThis, object)):
    """Settings Constructor

    Args:
        entity: personal user or team to use for Run.
        project: project name for the Run.

    Raises:
        Exception: if problem.

    """

    def __init__(  # pylint: disable=unused-argument
        self,
        base_url = None,
        api_key = None,
        anonymous=None,

        # how do we annotate that: dryrun==offline?
        mode = 'online',
        entity = None,
        project = None,
        group = None,
        job_type = None,
        run_id = None,
        run_name = None,
        run_notes = None,
        run_tags=None,

        # compatibility / error handling
        compat_version=None,  # set to "0.8" for safer defaults for older users
        strict=None,  # set to "on" to enforce current best practices (also "warn")
        problem='fatal',

        # dynamic settings
        system_sample_seconds=2,
        system_samples=15,
        heartbeat_seconds=30,

        # logging
        log_base_dir="wandb",
        log_dir="",
        log_user_spec="wandb-{timespec}-{pid}-debug.log",
        log_internal_spec="wandb-{timespec}-{pid}-debug-internal.log",
        log_user=None,
        log_internal=None,
        symlink=None,

        # where files are temporary stored when saving
        files_dir=None,
        data_base_dir="wandb",
        data_dir="",
        data_spec="wandb-{timespec}-{pid}-data.bin",
        run_base_dir="wandb",
        run_dir_spec="run-{timespec}-{pid}",
        program=None,
        notebook_name=None,
        disable_code=None,
        host=None,
        username=None,
        docker=None,
        start_time=None,
        console=None,

        # compute environment
        jupyter=None,
        windows=None,
        show_colors=None,
        show_emoji=None,
        show_console=None,
        show_info=None,
        show_warnings=None,
        show_errors=None,
        summary_errors=None,
        summary_warnings=None,

        # special
        _settings=None,
        _environ=None,
        _files=None,
        _early_logging=None,
    ):
        kwargs = locals()
        object.__setattr__(self, "_masked_keys", set(['self', '_frozen']))
        object.__setattr__(self, "_unsaved_keys",
                           set(['_settings', '_files', '_environ']))
        object.__setattr__(self, "_frozen", False)
        self._setup(kwargs)

        if _settings:
            self.update(_settings)
        files = _files or []
        for f in files:
            d = self._load(f)
            self.update(d)
        if _environ:
            l = _early_logging or logger
            inv_map = _build_inverse_map(env_prefix, env_settings)
            env_dict = dict()
            for k, v in six.iteritems(_environ):
                if not k.startswith(env_prefix):
                    continue
                setting_key = inv_map.get(k)
                if setting_key:
                    conv = env_convert.get(setting_key, None)
                    if conv:
                        v = conv(v)
                    env_dict[setting_key] = v
                else:
                    l.info("Unhandled environment var: {}".format(k))

            l.info("setting env: {}".format(env_dict))
            self.update(env_dict)

    def _clear_early_logging(self):
        # TODO(jhr): this is a hack
        object.__setattr__(self, "_early_logging", None)

    def _setup(self, kwargs):
        for k, v in six.iteritems(kwargs):
            if k not in self._unsaved_keys:
                object.__setattr__(self, k, v)

    def __copy__(self):
        """Copy (note that the copied object will not be frozen)."""
        s = Settings()
        s.update(dict(self))
        return s

    def duplicate(self):
        return copy.copy(self)

    def _check_invalid(self, k, v):
        # Check to see if matches choice
        f = defaults.get('_' + k)
        if f and isinstance(f, Field):
            if v is not None and f.choices and v not in f.choices:
                raise TypeError('Settings field {} set to {} not in {}'.format(
                    k, v, ','.join(f.choices)))

    def update(self, __d=None, **kwargs):
        if self._frozen and (__d or kwargs):
            raise TypeError('Settings object is frozen')
        d = __d or dict()
        for check in d, kwargs:
            for k in six.viewkeys(check):
                if k not in self.__dict__:
                    raise KeyError(k)
                self._check_invalid(k, check[k])
        self.__dict__.update({k: v for k, v in d.items() if v is not None})
        self.__dict__.update(
            {k: v
             for k, v in kwargs.items() if v is not None})

    def _probe(self):
        d = {}
        d['jupyter'] = _get_python_type() != "python"
        d['windows'] = platform.system() == "Windows"
        # disable symlinks if on windows (requires admin or developer setup)
        d['symlink'] = True
        if d['windows']:
            d['symlink'] = False
        self.setdefaults(d)

        # TODO(jhr): this needs to be moved last in setting up settings
        u = {}
        if self.console == 'auto':
            console = 'redirect'
            if self.jupyter:
                console = 'off'
            u['console'] = console
        self.update(u)

    def setdefaults(self, __d=None):
        __d = __d or defaults
        # set defaults
        for k, v in __d.items():
            if not k.startswith('_'):
                if self.__dict__.get(k) is None:
                    object.__setattr__(self, k, v)

    def save(self, fname):
        pass

    def load(self, fname):
        pass

    def __setattr__(self, name, value):
        if name not in self.__dict__:
            raise AttributeError(name)
        if self._frozen:
            raise TypeError('Settings object is frozen')
        self._check_invalid(name, value)
        object.__setattr__(self, name, value)

    def _apply_wandb_init_args(self, kwargs):
        unhandled_keys = tuple()
        return unhandled_keys

    def keys(self):
        return tuple(k for k in self.__dict__ if k not in self._masked_keys)

    def __getitem__(self, k):
        return self.__dict__[k]

    def freeze(self):
        object.__setattr__(self, "_frozen", True)
        return self

    @property
    def frozen(self):
        return self._frozen

    def _load(self, fname):
        section = 'default'
        cp = configparser.ConfigParser()
        cp.add_section(section)
        cp.read(fname)
        d = dict()
        for k in cp[section]:
            d[k] = cp[section][k]
        return d

    def apply_init(self, args):
        # strip out items where value is None
        param_map = dict(name='run_name', id='run_id', tags='run_tags')
        args = {
            param_map.get(k, k): v
            for k, v in six.iteritems(args) if v is not None
        }
        self.update(args)
