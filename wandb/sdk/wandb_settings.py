#
"""
This module configures settings for wandb runs.

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

When override is used, it has priority over non-override settings

Override priorities are in the reverse order of non-override settings

"""

import configparser
import copy
from datetime import datetime
from distutils.util import strtobool
import enum
import getpass
import itertools
import json
import os
import platform
import socket
import sys
import tempfile
import time

import six
import wandb
from wandb import util

from .lib.git import GitRepo
from .lib.ipython import _get_python_type
from .lib.runid import generate_id

if wandb.TYPE_CHECKING:  # type: ignore
    from typing import (  # noqa: F401 pylint: disable=unused-import
        Dict,
        List,
        Optional,
        Union,
        Tuple,
        Callable,
        Set,
        Type,
        Sequence,
    )

defaults: Dict[str, Union[str, int, Tuple]] = dict(
    base_url="https://api.wandb.ai",
    summary_warnings=5,
    git_remote="origin",
    ignore_globs=(),
)

# env mapping?
env_prefix: str = "WANDB_"
# env_override_suffix: str = "_OVERRIDE"
env_settings: Dict[str, Optional[str]] = dict(
    entity=None,
    project=None,
    base_url=None,
    api_key=None,
    sweep_id=None,
    mode=None,
    run_group=None,
    problem=None,
    console=None,
    config_paths=None,
    sweep_param_path=None,
    run_id=None,
    notebook_name=None,
    host=None,
    username=None,
    disable_code=None,
    anonymous=None,
    ignore_globs=None,
    resume=None,
    silent=None,
    sagemaker_disable=None,
    root_dir="WANDB_DIR",
    run_name="WANDB_NAME",
    run_notes="WANDB_NOTES",
    run_tags="WANDB_TAGS",
    run_job_type="WANDB_JOB_TYPE",
)

env_convert: Dict[str, Callable[[str], List[str]]] = dict(
    run_tags=lambda s: s.split(","), ignore_globs=lambda s: s.split(","),
)


def _build_inverse_map(prefix: str, d: Dict[str, str]) -> Dict[str, str]:
    inv_map = dict()
    for k, v in six.iteritems(d):
        v = v or prefix + k.upper()
        inv_map[v] = k
    return inv_map


def _error_choices(value: str, choices: Set[str]) -> str:
    return "{} not in {}".format(value, ",".join(list(choices)))


def _get_program():
    program = os.getenv(wandb.env.PROGRAM)
    if program:
        return program

    try:
        import __main__  # type: ignore

        return __main__.__file__
    except (ImportError, AttributeError):
        return None


def _get_program_relpath_from_gitrepo(program, _logger=None):
    repo = GitRepo()
    root = repo.root
    if not root:
        root = os.getcwd()
    full_path_to_program = os.path.join(
        root, os.path.relpath(os.getcwd(), root), program
    )
    if os.path.exists(full_path_to_program):
        relative_path = os.path.relpath(full_path_to_program, start=root)
        if "../" in relative_path:
            if _logger:
                _logger.warning("could not save program above cwd: %s" % program)
            return None
        return relative_path

    if _logger:
        _logger.warning("could not find program at %s" % program)
    return None


# the setting exposed to users as `dir=` or `WANDB_DIR` is actually
# the `root_dir`. We add the `__stage_dir__` to it to get the full
# `wandb_dir`
def get_wandb_dir(root_dir: str):
    # We use the hidden version if it already exists, otherwise non-hidden.
    if os.path.exists(os.path.join(root_dir, ".wandb")):
        __stage_dir__ = ".wandb" + os.sep
    else:
        __stage_dir__ = "wandb" + os.sep

    path = os.path.join(root_dir, __stage_dir__)
    if not os.access(root_dir or ".", os.W_OK):
        wandb.termwarn("Path %s wasn't writable, using system temp directory" % path)
        path = os.path.join(tempfile.gettempdir(), __stage_dir__ or ("wandb" + os.sep))

    return path


def _str_as_bool(val) -> Optional[bool]:
    try:
        val = bool(strtobool(val))
    except (AttributeError, ValueError):
        pass
    return val if isinstance(val, bool) else None


@enum.unique
class SettingsConsole(enum.Enum):
    OFF = 0
    WRAP = 1
    REDIRECT = 2


class Settings(object):
    """Settings Constructor

    Arguments:
        entity: personal user or team to use for Run.
        project: project name for the Run.

    Raises:
        Exception: if problem.
    """

    mode: str = "online"
    console: str = "auto"
    disabled: bool = False
    run_tags: Optional[Tuple] = None

    resume_fname_spec: Optional[str] = None
    root_dir: Optional[str] = None
    log_dir_spec: Optional[str] = None
    log_user_spec: Optional[str] = None
    log_internal_spec: Optional[str] = None
    sync_file_spec: Optional[str] = None
    sync_dir_spec: Optional[str] = None
    files_dir_spec: Optional[str] = None
    log_symlink_user_spec: Optional[str] = None
    log_symlink_internal_spec: Optional[str] = None
    sync_symlink_latest_spec: Optional[str] = None
    settings_system_spec: Optional[str] = None
    settings_workspace_spec: Optional[str] = None
    silent: bool = False
    show_info: bool = True
    show_warnings: bool = True
    show_errors: bool = True
    email: Optional[str] = None
    save_code: Optional[bool] = None
    program_relpath: Optional[str] = None

    # Public attributes
    entity: Optional[str] = None
    project: Optional[str] = None
    run_group: Optional[str] = None
    run_name: Optional[str] = None
    run_notes: Optional[str] = None
    sagemaker_disable: Optional[bool] = None

    # TODO(jhr): Audit these attributes
    run_job_type: Optional[str] = None
    base_url: Optional[str] = None

    # Private attributes
    __start_time: Optional[float]
    __start_datetime: Optional[datetime]

    # Internal attributes
    __frozen: bool
    __defaults_dict: Dict[str, int]
    __override_dict: Dict[str, int]
    __defaults_dict_set: Dict[str, Set[int]]
    __override_dict_set: Dict[str, Set[int]]

    @enum.unique
    class Source(enum.IntEnum):
        BASE: int = 1
        ORG: int = 2
        ENTITY: int = 3
        PROJECT: int = 4
        USER: int = 5
        SYSTEM: int = 6
        WORKSPACE: int = 7
        ENV: int = 8
        SETUP: int = 9
        LOGIN: int = 10
        INIT: int = 11
        SETTINGS: int = 12
        ARGS: int = 13

    Console: Type[SettingsConsole] = SettingsConsole

    def __init__(  # pylint: disable=unused-argument
        self,
        base_url: str = None,
        api_key: str = None,
        anonymous=None,
        mode: str = None,
        entity: str = None,
        project: str = None,
        run_group: str = None,
        run_job_type: str = None,
        run_id: str = None,
        run_name: str = None,
        run_notes: str = None,
        resume: str = None,
        magic: Union[Dict, str, bool] = False,
        run_tags: Sequence = None,
        sweep_id=None,
        allow_val_change: bool = None,
        force: bool = None,
        relogin: bool = None,
        # compatibility / error handling
        # compat_version=None,  # set to "0.8" for safer defaults for older users
        # strict=None,  # set to "on" to enforce current best practices (also "warn")
        problem="fatal",
        # dynamic settings
        system_sample_seconds=2,
        system_samples=15,
        heartbeat_seconds=30,
        config_paths=None,
        sweep_param_path=None,
        _config_dict=None,
        # directories and files
        root_dir=None,
        settings_system_spec="~/.config/wandb/settings",
        settings_workspace_spec="{wandb_dir}/settings",
        sync_dir_spec="{wandb_dir}/{run_mode}-{timespec}-{run_id}",
        sync_file_spec="run-{run_id}.wandb",
        # sync_symlink_sync_spec="{wandb_dir}/sync",
        # sync_symlink_offline_spec="{wandb_dir}/offline",
        sync_symlink_latest_spec="{wandb_dir}/latest-run",
        log_dir_spec="{wandb_dir}/{run_mode}-{timespec}-{run_id}/logs",
        log_user_spec="debug.log",
        log_internal_spec="debug-internal.log",
        log_symlink_user_spec="{wandb_dir}/debug.log",
        log_symlink_internal_spec="{wandb_dir}/debug-internal.log",
        resume_fname_spec="{wandb_dir}/wandb-resume.json",
        files_dir_spec="{wandb_dir}/{run_mode}-{timespec}-{run_id}/files",
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
        ignore_globs=None,
        save_code=None,
        program_relpath=None,
        git_remote=None,
        dev_prod=None,  # in old settings files, TODO: support?
        host=None,
        username=None,
        email=None,
        docker=None,
        sagemaker_disable: Optional[bool] = None,
        _start_time=None,
        _start_datetime=None,
        _cli_only_mode=None,  # avoid running any code specific for runs
        _disable_viewer=None,  # prevent early viewer query
        console=None,
        disabled=None,  # alias for mode=dryrun, not supported yet
        reinit=None,
        _save_requirements=True,
        # compute environment
        show_colors=None,
        show_emoji=None,
        silent=None,
        show_info=None,
        show_warnings=None,
        show_errors=None,
        summary_errors=None,
        summary_warnings=None,
        _internal_queue_timeout=2,
        _internal_check_process=8,
        _disable_meta=None,
        _disable_stats=None,
        _jupyter_path=None,
        _jupyter_name=None,
        _jupyter_root=None,
        _executable=None,
        _cuda=None,
        _args=None,
        _os=None,
        _python=None,
        _kaggle=None,
        _except_exit=None,
    ):
        kwargs = dict(locals())
        kwargs.pop("self")
        # Set up entries for all possible parameters
        self.__dict__.update({k: None for k in kwargs})
        # setup private attributes
        object.__setattr__(self, "_Settings__frozen", False)
        object.__setattr__(self, "_Settings__defaults_dict", dict())
        object.__setattr__(self, "_Settings__override_dict", dict())
        object.__setattr__(self, "_Settings__defaults_dict_set", dict())
        object.__setattr__(self, "_Settings__override_dict_set", dict())
        object.__setattr__(self, "_Settings__start_datetime", None)
        object.__setattr__(self, "_Settings__start_time", None)
        class_defaults = self._get_class_defaults()
        self._apply_defaults(class_defaults)
        self._apply_defaults(defaults)
        self._update(kwargs, _source=self.Source.SETTINGS)
        if os.environ.get(wandb.env.DIR) is None:
            self.root_dir = os.path.abspath(os.getcwd())

    @property
    def _offline(self) -> bool:
        ret = False
        if self.disabled:
            ret = True
        if self.mode in ("dryrun", "offline"):
            ret = True
        return ret

    @property
    def _silent(self) -> Optional[bool]:
        if not self.silent:
            return None
        return _str_as_bool(self.silent)

    @property
    def _show_info(self) -> Optional[bool]:
        if not self.show_info:
            return None
        return _str_as_bool(self.show_info)

    @property
    def _show_warnings(self) -> Optional[bool]:
        if not self.show_warnings:
            return None
        return _str_as_bool(self.show_warnings)

    @property
    def _show_errors(self) -> Optional[bool]:
        if not self.show_errors:
            return None
        return _str_as_bool(self.show_errors)

    @property
    def _noop(self) -> bool:
        return self.mode == "disabled"

    @property
    def _jupyter(self) -> bool:
        return _get_python_type() != "python"

    @property
    def _kaggle(self) -> bool:
        return util._is_kaggle()

    @property
    def _windows(self) -> bool:
        return platform.system() == "Windows"

    @property
    def _console(self) -> SettingsConsole:
        convert_dict: Dict[str, SettingsConsole] = dict(
            off=SettingsConsole.OFF,
            wrap=SettingsConsole.WRAP,
            redirect=SettingsConsole.REDIRECT,
        )
        console: str = self.console
        if console == "auto":
            if self._jupyter:
                console = "wrap"
            elif self._windows:
                console = "wrap"
                # legacy_env_var = "PYTHONLEGACYWINDOWSSTDIO"
                # if sys.version_info >= (3, 6) and legacy_env_var not in os.environ:
                #     msg = (
                #         "Set %s environment variable to enable"
                #         " proper console logging on Windows. Falling "
                #         "back to wrapping stdout/err." % legacy_env_var
                #     )
                #     wandb.termwarn(msg)
                #     logger.info(msg)
                #     console = "wrap"
                # if "tensorflow" in sys.modules:
                #     msg = (
                #         "Tensorflow detected. Stream redirection is not supported "
                #         "on Windows when tensorflow is imported. Falling back to "
                #         "wrapping stdout/err."
                #     )
                #     wandb.termlog(msg)
                #     logger.info(msg)
                #     console = "wrap"
                # else:
                #     console = "redirect"
            else:
                console = "redirect"
        convert: SettingsConsole = convert_dict[console]
        return convert

    @property
    def resume_fname(self) -> str:
        return self._path_convert(self.resume_fname_spec)

    @property
    def wandb_dir(self) -> str:
        return get_wandb_dir(self.root_dir or "")

    @property
    def log_user(self) -> str:
        return self._path_convert(self.log_dir_spec, self.log_user_spec)

    @property
    def log_internal(self) -> str:
        return self._path_convert(self.log_dir_spec, self.log_internal_spec)

    @property
    def _sync_dir(self) -> str:
        return self._path_convert(self.sync_dir_spec)

    @property
    def sync_file(self) -> str:
        return self._path_convert(self.sync_dir_spec, self.sync_file_spec)

    @property
    def files_dir(self) -> str:
        return self._path_convert(self.files_dir_spec)

    @property
    def log_symlink_user(self) -> str:
        return self._path_convert(self.log_symlink_user_spec)

    @property
    def log_symlink_internal(self) -> str:
        return self._path_convert(self.log_symlink_internal_spec)

    @property
    def sync_symlink_latest(self) -> str:
        return self._path_convert(self.sync_symlink_latest_spec)

    @property
    def settings_system(self) -> str:
        return self._path_convert(self.settings_system_spec)

    @property
    def settings_workspace(self) -> str:
        return self._path_convert(self.settings_workspace_spec)

    def _validate_mode(self, value):
        choices = {
            "dryrun",
            "run",
            "offline",
            "online",
            "disabled",
        }
        if value in choices:
            return
        return _error_choices(value, choices)

    def _validate_console(self, value):
        # choices = {"auto", "redirect", "off", "file", "iowrap", "notebook"}
        choices = {
            "auto",
            "redirect",
            "off",
            "wrap",
        }
        if value in choices:
            return
        return _error_choices(value, choices)

    def _validate_problem(self, value):
        choices = {"fatal", "warn", "silent"}
        if value in choices:
            return
        return _error_choices(value, choices)

    def _validate_anonymous(self, value):
        choices = {"allow", "must", "never", "false", "true"}
        if value in choices:
            return
        return _error_choices(value, choices)

    def _validate_silent(self, value):
        val = _str_as_bool(value)
        if val is None:
            return "{} is not a boolean".format(value)

    def _validate_show_info(self, value):
        val = _str_as_bool(value)
        if val is None:
            return "{} is not a boolean".format(value)

    def _validate_show_warnings(self, value):
        val = _str_as_bool(value)
        if val is None:
            return "{} is not a boolean".format(value)

    def _validate_show_errors(self, value):
        val = _str_as_bool(value)
        if val is None:
            return "{} is not a boolean".format(value)

    def _preprocess_base_url(self, value):
        if value is not None:
            value = value.rstrip("/")
        return value

    def _start_run(self):
        datetime_now: datetime = datetime.now()
        time_now: float = time.time()
        object.__setattr__(self, "_Settings__start_datetime", datetime_now)
        object.__setattr__(self, "_Settings__start_time", time_now)

    def _apply_settings(self, settings, _logger=None):
        # TODO(jhr): make a more efficient version of this
        for k in settings._public_keys():
            source = settings.__defaults_dict.get(k)
            self._update({k: settings[k]}, _source=source)

    def _apply_defaults(self, defaults):
        self._update(defaults, _source=self.Source.BASE)

    def _apply_configfiles(self, _logger=None):
        # TODO(jhr): permit setting of config in system and workspace
        self._update(self._load(self.settings_system), _source=self.Source.SYSTEM)

        self._update(self._load(self.settings_workspace), _source=self.Source.WORKSPACE)

    def _apply_environ(self, environ, _logger=None):
        inv_map = _build_inverse_map(env_prefix, env_settings)
        env_dict = dict()
        for k, v in six.iteritems(environ):
            if not k.startswith(env_prefix):
                continue
            setting_key = inv_map.get(k)
            if setting_key:
                conv = env_convert.get(setting_key, None)
                if conv:
                    v = conv(v)
                env_dict[setting_key] = v
            else:
                if _logger:
                    _logger.info("Unhandled environment var: {}".format(k))

        if _logger:
            _logger.info("setting env: {}".format(env_dict))
        self._update(env_dict, _source=self.Source.ENV)

    def _apply_user(self, user_settings, _logger=None):
        if _logger:
            _logger.info("setting user settings: {}".format(user_settings))
        self._update(user_settings, _source=self.Source.USER)

    def _apply_source_login(self, login_settings, _logger=None):
        if _logger:
            _logger.info("setting login settings: {}".format(login_settings))
        self._update(login_settings, _source=self.Source.LOGIN)

    def _path_convert_part(self, path_part, format_dict):
        """convert slashes, expand ~ and other macros."""

        path_parts = path_part.split(os.sep if os.sep in path_part else "/")
        for i in range(len(path_parts)):
            try:
                path_parts[i] = path_parts[i].format(**format_dict)
            except KeyError:
                return None
        return path_parts

    def _path_convert(self, *path):
        """convert slashes, expand ~ and other macros."""

        format_dict = dict()
        if self._start_time:
            format_dict["timespec"] = datetime.strftime(
                self._start_datetime, "%Y%m%d_%H%M%S"
            )
        if self.run_id:
            format_dict["run_id"] = self.run_id
        format_dict["run_mode"] = "offline-run" if self._offline else "run"
        format_dict["proc"] = os.getpid()
        # TODO(cling): hack to make sure we read from local settings
        #              this is wrong if the run_dir changes later
        format_dict["wandb_dir"] = self.wandb_dir or "wandb"

        path_items = []
        for p in path:
            part = self._path_convert_part(p, format_dict)
            if part is None:
                return None
            path_items += part
        path = os.path.join(*path_items)
        path = os.path.expanduser(path)
        return path

    # def _clear_early_logger(self):
    #     # TODO(jhr): this is a hack
    #     object.__setattr__(self, "_Settings__early_logger", None)

    def _setup(self, kwargs):
        for k, v in six.iteritems(kwargs):
            if k not in self._unsaved_keys:
                object.__setattr__(self, k, v)

    def __copy__(self):
        """Copy (note that the copied object will not be frozen)."""
        s = Settings()
        s._apply_settings(self)
        return s

    def duplicate(self):
        return copy.copy(self)

    def _check_invalid(self, k, v):
        if v is None:
            return
        f = getattr(self, "_validate_" + k, None)
        if not f or not callable(f):
            return
        invalid = f(v)
        if invalid:
            raise TypeError("Settings field {}: {}".format(k, invalid))

    def _perform_preprocess(self, k, v):
        f = getattr(self, "_preprocess_" + k, None)
        if not f or not callable(f):
            return v
        else:
            return f(v)

    def _update(self, __d=None, _source=None, _override=None, **kwargs):
        if self.__frozen and (__d or kwargs):
            raise TypeError("Settings object is frozen")
        d = __d or dict()
        data = {}
        for check in d, kwargs:
            for k in six.viewkeys(check):
                if k not in self.__dict__:
                    raise KeyError(k)
                v = self._perform_preprocess(k, check[k])
                self._check_invalid(k, v)
                data[k] = v
        for k, v in six.iteritems(data):
            if v is None:
                continue
            if self._priority_failed(k, source=_source, override=_override):
                continue
            if isinstance(v, list):
                v = tuple(v)
            self.__dict__[k] = v
            if _source:
                self.__defaults_dict[k] = _source
                self.__defaults_dict_set.setdefault(k, set()).add(_source)
            if _override:
                self.__override_dict[k] = _override
                self.__override_dict_set.setdefault(k, set()).add(_override)

    def update(self, __d=None, **kwargs):
        self._update(__d, **kwargs)

    def _priority_failed(
        self, k: str, source: Optional[int], override: Optional[int]
    ) -> bool:
        key_source: Optional[int] = self.__defaults_dict.get(k)
        key_override: Optional[int] = self.__override_dict.get(k)
        if not key_source or not source:
            return False
        if key_override and not override:
            return True
        if key_override and override and source > key_source:
            return True
        if not override and source < key_source:
            return True
        return False

    def _infer_settings_from_env(self):
        """Modify settings based on environment (for runs and cli)."""

        d = {}
        # disable symlinks if on windows (requires admin or developer setup)
        d["symlink"] = True
        if self._windows:
            d["symlink"] = False
        self.setdefaults(d)

        # TODO(jhr): this needs to be moved last in setting up settings
        u = {}

        # For code saving, only allow env var override if value from server is true, or
        # if no preference was specified.
        if (self.save_code is True or self.save_code is None) and os.getenv(
            wandb.env.SAVE_CODE
        ) is not None:
            u["save_code"] = wandb.env.should_save_code()

        # Attempt to get notebook information if not already set by the user
        if self._jupyter and (self.notebook_name is None or self.notebook_name == ""):
            meta = wandb.jupyter.notebook_metadata(self._silent)
            u["_jupyter_path"] = meta.get("path")
            u["_jupyter_name"] = meta.get("name")
            u["_jupyter_root"] = meta.get("root")

        # host and username are populated by env_settings above if their env
        # vars exist -- but if they don't, we'll fill them in here
        if not self.host:
            u["host"] = socket.gethostname()

        if not self.username:
            try:
                u["username"] = getpass.getuser()
            except KeyError:
                # getuser() could raise KeyError in restricted environments like
                # chroot jails or docker containers.  Return user id in these cases.
                u["username"] = str(os.getuid())

        u["_executable"] = sys.executable

        u["docker"] = wandb.env.get_docker(wandb.util.image_id_from_k8s())

        # TODO: we should use the cuda library to collect this
        if os.path.exists("/usr/local/cuda/version.txt"):
            with open("/usr/local/cuda/version.txt") as f:
                u["_cuda"] = f.read().split(" ")[-1].strip()
        u["_args"] = sys.argv[1:]
        u["_os"] = platform.platform(aliased=True)
        u["_python"] = platform.python_version()
        # hack to make sure we don't hang on windows
        if self._windows and self._except_exit is None:
            u["_except_exit"] = True

        self.update(u)

    def _infer_run_settings_from_env(self, _logger=None):
        """Modify settings based on environment (for runs only)."""
        if self.disable_code:
            self.update(dict(program="<code saving explicitly disabled>"))
            return

        # If there's not already a program file, infer it now.
        program = self.program or _get_program()
        if program:
            program_relpath = self.program_relpath or _get_program_relpath_from_gitrepo(
                program, _logger=_logger
            )
            self.update(dict(program=program, program_relpath=program_relpath))
        else:
            program = "<python with no main file>"
            self.update(dict(program=program))

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
        if self.__frozen:
            raise TypeError("Settings object is frozen")
        value = self._perform_preprocess(name, value)
        self._check_invalid(name, value)
        object.__setattr__(self, name, value)

    @classmethod
    def _property_keys(cls):
        return (k for k, v in vars(cls).items() if isinstance(v, property))

    @classmethod
    def _class_keys(cls):
        return (
            k
            for k, v in vars(cls).items()
            if not k.startswith("_") and not callable(v) and not isinstance(v, property)
        )

    @classmethod
    def _get_class_defaults(cls):
        class_keys = set(cls._class_keys())
        return dict(
            (k, v) for k, v in vars(cls).items() if k in class_keys and v is not None
        )

    def _public_keys(self):
        return filter(lambda x: not x.startswith("_Settings__"), self.__dict__)

    def keys(self):
        return itertools.chain(self._public_keys(), self._property_keys())

    def __getitem__(self, k):
        props = self._property_keys()
        if k in props:
            return getattr(self, k)
        return self.__dict__[k]

    def freeze(self):
        self.__frozen = True
        return self

    def is_frozen(self) -> bool:
        return self.__frozen

    def _load(self, fname):
        section = "default"
        cp = configparser.ConfigParser()
        cp.add_section(section)
        cp.read(fname)
        d = dict()
        for k in cp[section]:
            d[k] = cp[section][k]
            # TODO (cvp): we didn't do this in the old cli, but it seems necessary
            if k == "ignore_globs":
                d[k] = d[k].split(",")
        return d

    def _apply_login(self, args, _logger=None):
        param_map = dict(key="api_key", host="base_url",)
        args = {param_map.get(k, k): v for k, v in six.iteritems(args) if v is not None}
        self._apply_source_login(args, _logger=_logger)

    def _apply_init_login(self, args):
        # apply some init parameters dealing with login
        keys = {"mode"}
        args = {k: v for k, v in six.iteritems(args) if k in keys and v is not None}
        self._update(args, _source=self.Source.INIT)

    def _apply_init(self, args):
        # prevent setting project, entity if in sweep
        # TODO(jhr): these should be locked elements in the future
        if self.sweep_id:
            for key in ("project", "entity"):
                val = args.pop(key, None)
                if val:
                    wandb.termwarn(
                        "Ignored wandb.init() arg %s when running a sweep" % key
                    )

        # strip out items where value is None
        param_map = dict(
            name="run_name",
            id="run_id",
            tags="run_tags",
            group="run_group",
            job_type="run_job_type",
            notes="run_notes",
            dir="root_dir",
        )
        args = {param_map.get(k, k): v for k, v in six.iteritems(args) if v is not None}
        # fun logic to convert the resume init arg
        if args.get("resume") is not None:
            if isinstance(args["resume"], six.string_types):
                if args["resume"] not in ("allow", "must", "never", "auto"):
                    if args.get("run_id") is None:
                        #  TODO: deprecate or don't support
                        args["run_id"] = args["resume"]
                    args["resume"] = "allow"
            elif args["resume"] is True:
                args["resume"] = "auto"

        # update settings
        self._update(args, _source=self.Source.INIT)

        # handle auto resume logic
        if self.resume == "auto":
            if os.path.exists(self.resume_fname):
                with open(self.resume_fname) as f:
                    resume_run_id = json.load(f)["run_id"]
                if self.run_id is None:
                    self.run_id = resume_run_id
                elif self.run_id != resume_run_id:
                    wandb.termwarn(
                        "Tried to auto resume run with id %s but id %s is set."
                        % (resume_run_id, self.run_id)
                    )
        self.run_id = self.run_id or generate_id()
        # persist our run id incase of failure
        if self.resume == "auto":
            wandb.util.mkdir_exists_ok(self.wandb_dir)
            with open(self.resume_fname, "w") as f:
                f.write(json.dumps({"run_id": self.run_id}))

    def _as_source(self, source, override=None):
        return Settings._Setter(settings=self, source=source, override=override)

    class _Setter(object):
        def __init__(self, settings, source, override):
            object.__setattr__(self, "_settings", settings)
            object.__setattr__(self, "_source", source)
            object.__setattr__(self, "_override", override)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, exc_traceback):
            pass

        def __setattr__(self, name, value):
            self.update({name: value})

        def update(self, *args, **kwargs):
            kwargs.update(_source=self._source, _override=self._override)
            self._settings.update(*args, **kwargs)
