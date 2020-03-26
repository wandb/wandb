"""
settings.
"""
import six
import logging
import collections
import configparser

logger = logging.getLogger("wandb")

source = ("org", "team", "project", "sysdir", "dir", "env", "setup",
          "settings", "args")

Field = collections.namedtuple('TypedField', ['type', 'choices'])

defaults = dict(
    team=None,
    entity=None,
    project=None,
    base_url="https://api.wandb.ai",
    # base_url="http://api.wandb.test",
    api_key=None,
    anonymous=None,

    # how do we annotate that: dryrun==offline?
    mode='online',
    _mode=Field(str, ('noop', 'online', 'offline', 'dryrun', 'async')),
    group=None,
    job_type=None,

    # compatibility / error handling
    compat_version=None,  # set to "0.8" for safer defaults for older users
    strict=None,  # set to "on" to enforce current best practices (also "warn")
    problem='fatal',
    _problem=Field(str, ('fatal', 'warn', 'silent')),

    # dynamic settings
    system_sample_seconds=2,
    system_samples=15,
    heartbeat_seconds=30,
    log_base_dir="wandb",
    log_dir="",
    log_user_spec="wandb-{timespec}-{pid}-debug.log",
    log_internal_spec="wandb-{timespec}-{pid}-debug-internal.log",
    log_user=False,
    log_internal=True,

    # where files are temporary stored when saving
    files_dir="",
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
)

move_mapping = dict(entity="team", )

deprecate_mapping = dict(entity=True, )

# env mapping?
env_prefix = "WANDB_"
env_settings = dict(
    team=None,
    entity=None,
    project=None,
    base_url=None,
    mode=None,
    group="WANDB_RUN_GROUP",
    job_type=None,
    problem=None,
)


def _build_inverse_map(prefix, d):
    inv_map = dict()
    for k, v in six.iteritems(d):
        v = v or prefix + k.upper()
        inv_map[v] = k
    return inv_map


class Settings(object):
    def __init__(self,
                 settings=None,
                 environ=None,
                 files=None,
                 early_logging=None):
        _settings_dict = dict()
        for k, v in six.iteritems(defaults):
            if not k.startswith('_'):
                _settings_dict[k] = v
        # _forced_dict = dict()
        object.__setattr__(self, "_early_logging", early_logging)
        object.__setattr__(self, "_settings_dict", _settings_dict)
        # set source where force happened
        # object.__setattr__(self, "_forced_dict", _forced_dict)
        # set source where assignment happened
        # object.__setattr__(self, "_assignment_dict", _forced_dict)
        object.__setattr__(self, "_frozen", False)
        if settings:
            self.update(settings)
        files = files or []
        for f in files:
            d = self._load(f)
            self.update(d)
        if environ:
            inv_map = _build_inverse_map(env_prefix, env_settings)
            env_dict = dict()
            for k, v in six.iteritems(environ):
                if not k.startswith(env_prefix):
                    continue
                setting_key = inv_map.get(k)
                if setting_key:
                    env_dict[setting_key] = v
                else:
                    l = early_logging or logger
                    l.info("Unhandled environment var: {}".format(k))

            self.update(env_dict)

    def __copy__(self):
        s = Settings()
        s.update(dict(self))
        return s

    def _clear_early_logging(self):
        object.__setattr__(self, "_early_logging", None)

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
                if k not in self._settings_dict:
                    raise KeyError(k)
                self._check_invalid(k, check[k])

        self._settings_dict.update(d)
        self._settings_dict.update(kwargs)

    def _load(self, fname):
        section = 'default'
        cp = configparser.ConfigParser()
        cp.add_section(section)
        cp.read(fname)
        d = dict()
        for k in cp[section]:
            d[k] = cp[section][k]
        return d

    def __getattr__(self, k):
        try:
            v = self._settings_dict[k]
        except KeyError:
            raise AttributeError(k)
        return v

    def __setattr__(self, k, v):
        if self._frozen:
            raise TypeError('Settings object is frozen')
        if k not in self._settings_dict:
            raise AttributeError(k)
        self._check_invalid(k, v)
        self._settings_dict[k] = v

    def keys(self):
        return self._settings_dict.keys()

    def __getitem__(self, k):
        return self._settings_dict[k]

    def freeze(self):
        object.__setattr__(self, "_frozen", True)
