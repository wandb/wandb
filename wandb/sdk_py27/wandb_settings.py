"""Settings.

This module configures settings which impact wandb runs.

Order of loading settings: (differs from priority)
    defaults
    environment
    wandb.setup(settings=)
    system_config
    workspace_config
    wandb.init(settings=)
    network_org
    network_entity
    network_project

Priority of settings:  See "source" variable.

"""

import collections
import configparser
import copy
import datetime
import logging
import os
import platform

import shortuuid  # type: ignore
import six
import wandb

if wandb.TYPE_CHECKING:  # type: ignore
    from typing import (  # noqa: F401 pylint: disable=unused-import
        Dict,
        List,
        Optional,
        Union,
    )

logger = logging.getLogger("wandb")

source = (
    "org",
    "entity",
    "project",
    "system",
    "workspace",
    "env",
    "setup",
    "settings",
    "args",
)

Field = collections.namedtuple("TypedField", ["type", "choices"])


def _generate_id():
    # ~3t run ids (36**8)
    run_gen = shortuuid.ShortUUID(alphabet=list("0123456789abcdefghijklmnopqrstuvwxyz"))
    return run_gen.random(8)


defaults = dict(
    base_url="https://api.wandb.ai",
    show_warnings=2,
    summary_warnings=5,
    _mode=Field(str, ("auto", "noop", "online", "offline", "dryrun", "run",)),
    _problem=Field(str, ("fatal", "warn", "silent",)),
    console="auto",
    _console=Field(str, ("auto", "redirect", "off", "mock", "file", "iowrap",)),
)

# env mapping?
env_prefix = "WANDB_"
env_settings = dict(
    entity=None,
    project=None,
    base_url=None,
    sweep_id=None,
    mode=None,
    run_group=None,
    job_type=None,
    problem=None,
    console=None,
    config_paths=None,
    run_id=None,
    run_name="WANDB_NAME",
    run_notes="WANDB_NOTES",
    run_tags="WANDB_TAGS",
)

env_convert = dict(run_tags=lambda s: s.split(","),)


def _build_inverse_map(prefix, d):
    inv_map = dict()
    for k, v in six.iteritems(d):
        v = v or prefix + k.upper()
        inv_map[v] = k
    return inv_map


def _get_python_type():
    try:
        if "terminal" in get_ipython().__module__:
            return "ipython"
        else:
            return "jupyter"
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
        mode = "online",
        entity = None,
        project = None,
        run_group = None,
        job_type = None,
        run_id = None,
        run_name = None,
        run_notes = None,
        run_tags=None,
        sweep_id=None,
        # compatibility / error handling
        compat_version=None,  # set to "0.8" for safer defaults for older users
        strict=None,  # set to "on" to enforce current best practices (also "warn")
        problem="fatal",
        # dynamic settings
        system_sample_seconds=2,
        system_samples=15,
        heartbeat_seconds=30,
        config_paths=None,
        _config_dict=None,
        # directories and files
        wandb_dir="wandb",
        settings_system_spec="~/.config/wandb/settings",
        settings_workspace_spec="{wandb_dir}/settings",
        settings_system=None,  # computed
        settings_workspace=None,  # computed
        sync_dir_spec="{wandb_dir}/runs/run-{timespec}-{run_id}",
        sync_file_spec="run-{timespec}-{run_id}.wandb",
        # sync_symlink_sync_spec="{wandb_dir}/sync",
        # sync_symlink_offline_spec="{wandb_dir}/offline",
        sync_symlink_latest_spec="{wandb_dir}/latest",
        sync_file=None,  # computed
        log_dir_spec="{wandb_dir}/runs/run-{timespec}-{run_id}/logs",
        log_user_spec="debug-{timespec}-{run_id}.log",
        log_internal_spec="debug-internal-{timespec}-{run_id}.log",
        log_symlink_user_spec="{wandb_dir}/debug.log",
        log_symlink_internal_spec="{wandb_dir}/debug-internal.log",
        log_user=None,  # computed
        log_internal=None,  # computed
        files_dir_spec="{wandb_dir}/runs/run-{timespec}-{run_id}/files",
        files_dir=None,  # computed
        symlink=None,  # probed
        # where files are temporary stored when saving
        # files_dir=None,
        # data_base_dir="wandb",
        # data_dir="",
        # data_spec="wandb-{timespec}-{pid}-data.bin",
        # run_base_dir="wandb",
        # run_dir_spec="run-{timespec}-{pid}",
        program=None,
        notebook_name=None,
        disable_code=None,
        host=None,
        username=None,
        docker=None,
        _start_time=None,
        _start_datetime=None,
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
        _early_logger=None,
        _internal_queue_timeout=2,
        _internal_check_process=8,
    ):
        kwargs = locals()
        object.__setattr__(self, "_masked_keys", set(["self", "_frozen"]))
        object.__setattr__(
            self, "_unsaved_keys", set(["_settings", "_files", "_environ"])
        )
        object.__setattr__(self, "_frozen", False)
        object.__setattr__(self, "_locked_by", dict)
        object.__setattr__(self, "_configured_by", dict)
        self._setup(kwargs)

        if _environ:
            _logger = _early_logger or logger
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
                    _logger.info("Unhandled environment var: {}".format(k))

            _logger.info("setting env: {}".format(env_dict))
            self.update(env_dict, _setter="env")
        if _files:
            # TODO(jhr): permit setting of config in system and workspace
            settings_system = self._path_convert(
                self.__dict__.get("settings_system_spec")
            )
            self.update(self._load(settings_system), _setter="system")
            settings_workspace = self._path_convert(
                self.__dict__.get("settings_workspace_spec")
            )
            self.update(self._load(settings_workspace), _setter="workspace")
        if _settings:
            self.update(_settings)

    def _path_convert_part(self, path_part, format_dict):
        """convert slashes, expand ~ and other macros."""

        path_parts = path_part.split(os.sep if os.sep in path_part else "/")
        for i in range(len(path_parts)):
            path_parts[i] = path_parts[i].format(**format_dict)
        return path_parts

    def _path_convert(self, *path):
        """convert slashes, expand ~ and other macros."""

        format_dict = dict()
        if self._start_time:
            format_dict["timespec"] = datetime.datetime.strftime(
                self._start_datetime, "%Y%m%d_%H%M%S"
            )
        if self.run_id:
            format_dict["run_id"] = self.run_id
        format_dict["proc"] = os.getpid()
        format_dict["wandb_dir"] = self.wandb_dir

        path_items = []
        for p in path:
            path_items += self._path_convert_part(p, format_dict)
        path = os.path.join(*path_items)
        path = os.path.expanduser(path)
        return path

    def _clear_early_logger(self):
        # TODO(jhr): this is a hack
        object.__setattr__(self, "_early_logger", None)

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
        f = defaults.get("_" + k)
        if f and isinstance(f, Field):
            if v is not None and f.choices and v not in f.choices:
                raise TypeError(
                    "Settings field {} set to {} not in {}".format(
                        k, v, ",".join(f.choices)
                    )
                )

    def update(self, __d=None, _setter=None, **kwargs):
        if self._frozen and (__d or kwargs):
            raise TypeError("Settings object is frozen")
        d = __d or dict()
        for check in d, kwargs:
            for k in six.viewkeys(check):
                if k not in self.__dict__:
                    raise KeyError(k)
                self._check_invalid(k, check[k])
        self.__dict__.update({k: v for k, v in d.items() if v is not None})
        self.__dict__.update({k: v for k, v in kwargs.items() if v is not None})

    def _probe(self):
        d = {}
        d["jupyter"] = _get_python_type() != "python"
        d["windows"] = platform.system() == "Windows"
        # disable symlinks if on windows (requires admin or developer setup)
        d["symlink"] = True
        if d["windows"]:
            d["symlink"] = False
        self.setdefaults(d)

        # TODO(jhr): this needs to be moved last in setting up settings
        u = {}
        if self.console == "auto":
            console = "redirect"
            if self.jupyter:
                console = "off"
            u["console"] = console
        self.update(u)

    def setdefaults(self, __d=None):
        __d = __d or defaults
        # set defaults
        for k, v in __d.items():
            if not k.startswith("_"):
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
            raise TypeError("Settings object is frozen")
        self._check_invalid(name, value)
        object.__setattr__(self, name, value)

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
        section = "default"
        cp = configparser.ConfigParser()
        cp.add_section(section)
        cp.read(fname)
        d = dict()
        for k in cp[section]:
            d[k] = cp[section][k]
        return d

    def apply_init(self, args):
        # strip out items where value is None
        param_map = dict(
            name="run_name", id="run_id", tags="run_tags", group="run_group",
        )
        args = {param_map.get(k, k): v for k, v in six.iteritems(args) if v is not None}
        self.update(args)
        self.run_id = self.run_id or _generate_id()
