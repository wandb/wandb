import configparser
from datetime import datetime
from distutils.util import strtobool
import enum
import getpass
import json
import multiprocessing
import os
import platform
import re
import socket
import sys
import tempfile
import time
from typing import (
    Any,
    Callable,
    cast,
    Dict,
    FrozenSet,
    Mapping,
    no_type_check,
    Optional,
    Set,
    Sequence,
    Type,
    TYPE_CHECKING,
    Union,
)
from urllib.parse import urljoin

import wandb
from wandb import util
from wandb.errors import UsageError
from wandb.sdk.wandb_config import Config
from wandb.sdk.wandb_setup import _EarlyLogger

from .lib.git import GitRepo
from .lib.ipython import _get_python_type
from .lib.runid import generate_id


def get_wandb_dir(root_dir: str) -> str:
    """
    Get the full path to the wandb directory.

    The setting exposed to users as `dir=` or `WANDB_DIR` is the `root_dir`.
    We add the `__stage_dir__` to it to get the full `wandb_dir`
    """
    # We use the hidden version if it already exists, otherwise non-hidden.
    if os.path.exists(os.path.join(root_dir, ".wandb")):
        __stage_dir__ = ".wandb" + os.sep
    else:
        __stage_dir__ = "wandb" + os.sep

    path = os.path.join(root_dir, __stage_dir__)
    if not os.access(root_dir or ".", os.W_OK):
        wandb.termwarn(f"Path {path} wasn't writable, using system temp directory")
        path = os.path.join(tempfile.gettempdir(), __stage_dir__ or ("wandb" + os.sep))

    return os.path.expanduser(path)


def _str_as_bool(val: Union[str, bool, None]) -> Optional[bool]:
    """
    Parse a string as a bool.
    """
    ret_val: Optional[bool] = None
    if isinstance(val, bool):
        return val
    try:
        ret_val = bool(strtobool(val))
    except (AttributeError, ValueError):
        pass
    return ret_val


def _path_convert(*args: str) -> str:
    """
    Join path and apply os.path.expanduser to it.
    """
    return os.path.expanduser(os.path.join(*args))


def _redact_dict(
    d: Dict[str, Any],
    unsafe_keys: Union[Set[str], FrozenSet[str]] = frozenset({"api_key"}),
    redact_str: str = "***REDACTED***",
) -> Dict[str, Any]:
    """Redact a dict of unsafe values specified by their key."""
    if not d or unsafe_keys.isdisjoint(d):
        return d
    safe_dict = d.copy()
    safe_dict.update({k: redact_str for k in unsafe_keys.intersection(d)})
    return safe_dict


def _get_program() -> Optional[Any]:
    program = os.getenv(wandb.env.PROGRAM)
    if program is not None:
        return program
    try:
        import __main__  # type: ignore
        return __main__.__file__
    except (ImportError, AttributeError):
        return None


def _get_program_relpath_from_gitrepo(
    program: str, _logger: Optional[_EarlyLogger] = None
) -> Optional[str]:
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
            if _logger is not None:
                _logger.warning(f"Could not save program above cwd: {program}")
            return None
        return relative_path

    if _logger is not None:
        _logger.warning(f"Could not find program at {program}")
    return None


@enum.unique
class Source(enum.IntEnum):
    OVERRIDE: int = 0
    BASE: int = 1  # fixme: audit this
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


@enum.unique
class SettingsConsole(enum.Enum):
    OFF = 0
    WRAP = 1
    REDIRECT = 2

    def __repr__(self):
        return str(self.value)


class Property:
    """
    A class to represent attributes (individual settings) of the Settings object.

        - Encapsulates the logic of how to preprocess and validate values of settings
          throughout the lifetime of a class instance.
        - Allows for runtime modification of settings with hooks, e.g. in the case when
          a setting depends on another setting.
        - The update() method is used to update the value of a setting.
        - The `is_policy` attribute determines the source priority when updating the property value.
          E.g. if `is_policy` is True, the smallest `Source` value takes precedence.
    """
    def __init__(  # pylint: disable=unused-argument
        self,
        name: str,
        value: Optional[Any] = None,
        preprocessor: Union[Callable, Sequence[Callable], None] = None,
        validator: Union[Callable, Sequence[Callable], None] = None,
        # runtime converter (hook): properties can be e.g. tied to other properties
        hook: Union[Callable, Sequence[Callable], None] = None,
        is_policy: bool = False,
        frozen: bool = False,
        source: int = Source.BASE,
        **kwargs,
    ):
        self.name = name
        self._preprocessor = preprocessor
        self._validator = validator
        self._hook = hook
        self._is_policy = is_policy
        if TYPE_CHECKING:
            source = cast(Optional[int], source)
        self._source = source

        # preprocess and validate value
        self._value = self._validate(self._preprocess(value))

        self.__frozen = frozen

    @property
    def value(self) -> Any:
        """Apply the runtime modifier(s) (if any) and return the value."""
        _value = self._value
        if _value is not None and self._hook is not None:
            _hook = [self._hook] if callable(self._hook) else self._hook
            for h in _hook:
                _value = h(_value)
        return _value

    def _preprocess(self, value: Any) -> Any:
        if value is not None and self._preprocessor is not None:
            _preprocessor = [self._preprocessor] if callable(self._preprocessor) else self._preprocessor
            for p in _preprocessor:
                value = p(value)
        return value

    def _validate(self, value: Any) -> Any:
        if value is not None and self._validator is not None:
            _validator = [self._validator] if callable(self._validator) else self._validator
            for v in _validator:
                if not v(value):
                    raise ValueError(f"Invalid value for property {self.name}: {value}")
        return value

    def update(
        self,
        value: Any,
        source: Optional[int] = Source.OVERRIDE,
    ):
        """Update the value of the property."""
        if self.__frozen:
            raise TypeError("Property object is frozen")
        if TYPE_CHECKING:
            source = cast(Optional[int], source)
        # - always update value if source == Source.OVERRIDE
        # - if not previously overridden:
        #   - update value if source is lower than or equal to current source and property is policy
        #   - update value if source is higher than or equal to current source and property is not policy
        if (
            (source == Source.OVERRIDE)
            or (self._is_policy and self._source != Source.OVERRIDE and source <= self._source)
            or (not self._is_policy and self._source != Source.OVERRIDE and source >= self._source)
        ):
            # self.__dict__["_value"] = self._validate(self._preprocess(value))
            self._value = self._validate(self._preprocess(value))
            self._source = source

    def __setattr__(self, key, value):
        if "_Property__frozen" in self.__dict__ and self.__frozen:
            raise TypeError(f"Property object {self.name} is frozen")
        if key == "value":
            raise AttributeError("Use update() to update property value")
        self.__dict__[key] = value

    def __repr__(self):
        # return f"<Property {self.name}: value={self.value} source={self._source}>"
        # return f"<Property {self.name}: value={self._value}>"
        # return self.__dict__.__repr__()
        return f"{self.value}"


class Settings:
    """
    Settings for the wandb client.
    """

    Console: Type[SettingsConsole] = SettingsConsole

    # helper methods for pre-processing values
    def _join_with_base_url(self, url: str) -> str:
        return urljoin(self.base_url, url)

    # helper methods for validating values
    @staticmethod
    def _validate_mode(value: str) -> bool:
        choices: Set[str] = {"dryrun", "run", "offline", "online", "disabled"}
        if value not in choices:
            raise UsageError(f"Settings field `mode`: '{value}' not in {choices}")
        return True

    @staticmethod
    def _validate_project(value: Optional[str]) -> bool:
        invalid_chars_list = list("/\\#?%:")
        if value is not None:
            if len(value) > 128:
                raise UsageError(f'Invalid project name "{value}": exceeded 128 characters')
            invalid_chars = set([char for char in invalid_chars_list if char in value])
            if invalid_chars:
                raise UsageError(
                    f'Invalid project name "{value}": '
                    f"cannot contain characters \"{','.join(invalid_chars_list)}\", "
                    f"found \"{','.join(invalid_chars)}\""
                )
        return True

    @staticmethod
    def _validate_start_method(value: str) -> bool:
        available_methods = ["thread"]
        if hasattr(multiprocessing, "get_all_start_methods"):
            available_methods += multiprocessing.get_all_start_methods()
        if value not in available_methods:
            raise UsageError(f"Settings field `start_method`: '{value}' not in {available_methods}")
        return True

    @staticmethod
    def _validate_console(value: str) -> bool:
        # choices = {"auto", "redirect", "off", "file", "iowrap", "notebook"}
        choices: Set[str] = {"auto", "redirect", "off", "wrap"}
        if value not in choices:
            raise UsageError(f"Settings field `console`: '{value}' not in {choices}")
        return True

    @staticmethod
    def _validate_problem(value: str) -> bool:
        choices: Set[str] = {"fatal", "warn", "silent"}
        if value not in choices:
            raise UsageError(f"Settings field `problem`: '{value}' not in {choices}")
        return True

    @staticmethod
    def _validate_anonymous(value: str) -> bool:
        choices: Set[str] = {"allow", "must", "never", "false", "true"}
        if value not in choices:
            raise UsageError(f"Settings field `anonymous`: '{value}' not in {choices}")
        return True

    @staticmethod
    def _validate_base_url(value: Optional[str]) -> bool:
        if value is not None:
            if re.match(r".*wandb\.ai[^\.]*$", value) and "api." not in value:
                # user might guess app.wandb.ai or wandb.ai is the default cloud server
                raise UsageError(f"{value} is not a valid server address, did you mean https://api.wandb.ai?")
            elif re.match(r".*wandb\.ai[^\.]*$", value) and "http://" in value:
                raise UsageError("http is not secure, please use https://api.wandb.ai")
        return True

    # other helper methods
    def _start_run(self) -> None:
        time_stamp: float = time.time()
        datetime_now: datetime = datetime.fromtimestamp(time_stamp)
        object.__setattr__(self, "_Settings_start_datetime", datetime_now)
        object.__setattr__(self, "_Settings_start_time", time_stamp)

    def __init__(
        self,
        **kwargs: Any,
    ) -> None:
        self.__frozen: bool = False
        self.__initialized: bool = False

        # at init, explicitly assign attributes for static type checking purposes
        # once initialized, attributes are to be updated using the update method
        self._args: Any = {
            "validator": lambda x: isinstance(x, Sequence),
        }
        self._cli_only_mode: Any = {
            "validator": lambda x: isinstance(x, bool),
            "help": "Avoid running any code specific for runs",
        }
        self._config_dict: Any = {
            "validator": lambda x: isinstance(x, Config),
        }
        self._cuda: Any = {
            "validator": lambda x: isinstance(x, bool),
        }
        self._debug_log: Any = {
            "validator": lambda x: isinstance(x, str),
        }
        self._disable_meta: Any = {
            "validator": lambda x: isinstance(x, bool),
        }
        self._disable_stats: Any = {
            "validator": lambda x: isinstance(x, bool),
        }
        self._disable_viewer: Any = {
            "validator": lambda x: isinstance(x, bool),
            "help": "Prevent early viewer query",
        }
        self._except_exit: Any = {
            # fixme? elsewhere it is str
            "validator": lambda x: isinstance(x, bool),
        }
        self._executable: Any = {
            "validator": lambda x: isinstance(x, str),
        }
        self._internal_check_process: Any = {
            "value": 8,
            "validator": lambda x: isinstance(x, (int, float)),
        }
        self._internal_queue_timeout: Any = {
            "value": 2,
            "validator": lambda x: isinstance(x, (int, float)),
        }
        self._jupyter_name: Any = {
            "validator": lambda x: isinstance(x, str),
        }
        self._jupyter_path: Any = {
            "validator": lambda x: isinstance(x, str),
        }
        self._jupyter_root: Any = {
            "validator": lambda x: isinstance(x, str),
        }
        self._os: Any = {
            "validator": lambda x: isinstance(x, str),
        }
        self._python: Any = {
            "validator": lambda x: isinstance(x, str),
        }
        self._quiet: Any = {
            "preprocessor": _str_as_bool,
            "validator": lambda x: isinstance(x, bool),
        }
        self._require_service: Any = {
            "validator": lambda x: isinstance(x, str),
        }
        self._runqueue_item_id: Any = {
            "validator": lambda x: isinstance(x, str),
        }
        self._save_requirements: Any = {
            "value": True,
            "validator": lambda x: isinstance(x, bool),
        }
        self._service_transport: Any = {
            "validator": lambda x: isinstance(x, str),
        }
        self._start_datetime: Any = {
            "validator": lambda x: isinstance(x, datetime),
        }
        # self._start_datetime: Any = Property(name="_start_datetime", validator=lambda x: isinstance(x, datetime))
        self._start_time: Any = {
            "validator": lambda x: isinstance(x, float),
        }
        self._tmp_code_dir: Any = {
            "value": "code",
            "validator": lambda x: isinstance(x, str),
            "hook": lambda x: _path_convert(self.tmp_dir, x),
        }
        self._unsaved_keys: Any = {
            "validator": lambda x: isinstance(x, list) and all(isinstance(y, str) for y in x),
        }
        self.allow_val_change: Any = {
            "validator": lambda x: isinstance(x, bool),
        }
        self.anonymous: Any = {
            "validator": [
                lambda x: isinstance(x, str),
                self._validate_anonymous
            ],
        }
        self.api_key: Any = {
            # do not preprocess api_key: as @kptkin says, it's like changing the password
            "validator": [
                lambda x: isinstance(x, str)
            ],
        }
        self.base_url: Any = {
            "value": "https://api.wandb.ai",
            "preprocessor": lambda x: str(x).rstrip("/"),
            "validator": [
                lambda x: isinstance(x, str),
                self._validate_base_url,
            ],
            "help": "The base url for the wandb api.",
        }
        self.code_dir: Any = {
            "validator": lambda x: isinstance(x, str),
        }
        self.config_paths: Any = {
            "validator": lambda x: isinstance(x, Sequence) and all(isinstance(y, str) for y in x),
        }
        self.console: Any = {
            "value": "auto",
            "validator": [
                lambda x: isinstance(x, str),
                self._validate_console,
            ],
        }
        self.disable_code: Any = {
            "validator": lambda x: isinstance(x, bool),
            "is_priority": True,
        }
        self.disable_git: Any = {
            "validator": lambda x: isinstance(x, bool),
            "is_priority": True,
        }
        self.disabled: Any = {
            "value": False,
            "validator": lambda x: isinstance(x, bool),
            "help": "Alias for mode=dryrun, not supported yet",
        }
        self.docker: Any = {
            "validator": lambda x: isinstance(x, str),
        }
        self.email: Any = {
            "value": "False",
            "validator": lambda x: isinstance(x, str),
        }
        self.entity: Any = {
            "validator": lambda x: isinstance(x, str),
        }
        self.files_dir: Any = {
            "value": "files",
            "validator": lambda x: isinstance(x, str),
            "hook": lambda x: _path_convert(self.wandb_dir, f"{self.run_mode}-{self.timespec}-{self.run_id}", x),
        }
        self.force: Any = {
            "validator": lambda x: isinstance(x, bool),
        }
        self.git_remote: Any = {
            "value": "origin",
            "validator": lambda x: isinstance(x, str),
        }
        self.heartbeat_seconds: Any = {
            "value": 30,
            "validator": lambda x: isinstance(x, int),
        }
        self.host: Any = {
            "validator": lambda x: isinstance(x, str),
        }
        self.ignore_globs: Any = {
            "value": tuple(),
            "preprocessor": lambda x: tuple(x) if not isinstance(x, tuple) else x,
            "validator": lambda x: isinstance(x, tuple) and all(isinstance(y, str) for y in x),
        }
        self.label_disable: Any = {
            "validator": lambda x: isinstance(x, bool),
        }
        self.launch: Any = {
            "validator": lambda x: isinstance(x, bool),
        }
        self.launch_config_path: Any = {
            "validator": lambda x: isinstance(x, str),
        }
        self.log_dir: Any = {
            "value": "logs",
            "validator": lambda x: isinstance(x, str),
            "hook": lambda x: _path_convert(self.wandb_dir, f"{self.run_mode}-{self.timespec}-{self.run_id}", x),
        }
        self.log_internal: Any = {
            "value": "debug-internal.log",
            "validator": lambda x: isinstance(x, str),
            "hook": lambda x: _path_convert(self.log_dir, x),
        }
        self.log_symlink_internal: Any = {
            "value": "debug-internal.log",
            "validator": lambda x: isinstance(x, str),
            "hook": lambda x: _path_convert(self.wandb_dir, x),
        }
        self.log_symlink_user: Any = {
            "value": "debug.log",
            "validator": lambda x: isinstance(x, str),
            "hook": lambda x: _path_convert(self.wandb_dir, x),
        }
        self.log_user: Any = {
            "value": "debug.log",
            "validator": lambda x: isinstance(x, str),
            "hook": lambda x: _path_convert(self.log_dir, x),
        }
        self.login_timeout: Any = {
            "preprocessor": lambda x: float(x),
            "validator": lambda x: isinstance(x, float),
        }
        self.magic: Any = {
            "validator": lambda x: isinstance(x, (str, bool, dict)),
        }
        self.mode: Any = {
            "value": "online",
            "validator": [
                lambda x: isinstance(x, str),
                self._validate_mode,
            ],
        }
        self.notebook_name: Any = {
            "validator": lambda x: isinstance(x, str),
        }
        self.problem: Any = {
            "value": "fatal",
            "validator": [
                lambda x: isinstance(x, str),
                self._validate_problem
            ],
        }
        self.program: Any = {
            "validator": lambda x: isinstance(x, str),
        }
        self.program_relpath: Any = {
            "validator": lambda x: isinstance(x, str),
        }
        self.project: Any = {
            "validator": [
                lambda x: isinstance(x, str),
                self._validate_project,
            ],
        }
        self.reinit: Any = {
            "validator": lambda x: isinstance(x, bool),
        }
        self.relogin: Any = {
            "validator": lambda x: isinstance(x, bool),
        }
        self.resume: Any = {
            "validator": lambda x: isinstance(x, str),
        }
        self.resume_fname: Any = {
            "value": "wandb-resume.json",
            "validator": lambda x: isinstance(x, str),
            "hook": lambda x: _path_convert(self.wandb_dir, x),
        }
        self.root_dir: Any = {
            "validator": lambda x: isinstance(x, str),
        }
        self.run_group: Any = {
            "validator": lambda x: isinstance(x, str),
        }
        self.run_id: Any = {
            "validator": lambda x: isinstance(x, str),
        }
        self.run_job_type: Any = {  # TODO(jhr): Audit this
            "validator": lambda x: isinstance(x, str),
        }
        self.run_name: Any = {
            "validator": lambda x: isinstance(x, str),
        }
        self.run_notes: Any = {
            "validator": lambda x: isinstance(x, str),
        }
        self.run_tags: Any = {
            "validator": lambda x: isinstance(x, tuple),
        }
        self.sagemaker_disable: Any = {
            "validator": lambda x: isinstance(x, bool),
        }
        self.save_code: Any = {
            "validator": lambda x: isinstance(x, bool),
            "is_priority": True,
        }
        self.settings_system: Any = {
            "value": "~/.config/wandb/settings",
            "validator": lambda x: isinstance(x, str),
            "hook": lambda x: _path_convert(x),
        }
        self.settings_workspace: Any = {
            "value": "settings",
            "validator": lambda x: isinstance(x, str),
            "hook": lambda x: _path_convert(self.wandb_dir, x),
        }
        self.show_colors: Any = {
            "validator": lambda x: isinstance(x, bool),
        }
        self.show_emoji: Any = {
            "validator": lambda x: isinstance(x, bool),
        }
        self.show_errors: Any = {
            "value": "True",
            "preprocessor": _str_as_bool,
            "validator": lambda x: isinstance(x, bool),
        }
        self.show_info: Any = {
            "value": "True",
            "preprocessor": _str_as_bool,
            "validator": lambda x: isinstance(x, bool),
        }
        self.show_warnings: Any = {
            "value": "True",
            "preprocessor": _str_as_bool,
            "validator": lambda x: isinstance(x, bool),
        }
        self.silent: Any = {
            "value": "False",
            "preprocessor": _str_as_bool,
            "validator": lambda x: isinstance(x, bool),
        }
        self.start_method: Any = {
            "validator": [
                lambda x: isinstance(x, str),
                self._validate_start_method,
            ],
        }
        self.strict: Any = {
            "preprocessor": _str_as_bool,
            "validator": lambda x: isinstance(x, bool),
        }
        self.summary_errors: Any = {
            "validator": lambda x: isinstance(x, int),
        }
        self.summary_warnings: Any = {
            "value": 5,
            "preprocessor": lambda x: int(x),
            "validator": lambda x: isinstance(x, int),
            "is_policy": True,
        }
        self.sweep_id: Any = {
            "validator": lambda x: isinstance(x, str),
        }
        self.sweep_param_path: Any = {
            "validator": lambda x: isinstance(x, str),
        }
        self.symlink: Any = {
            "validator": lambda x: isinstance(x, bool),  # probed
        }
        self.sync_dir: Any = {
            "value": "<sync_dir>",
            "validator": lambda x: isinstance(x, str),
            "hook": [
                lambda x: _path_convert(self.wandb_dir, f"{self.run_mode}-{self.timespec}-{self.run_id}")
            ],
        }
        self.sync_file: Any = {
            "value": "run-<run_id>.wandb",
            "validator": lambda x: isinstance(x, str),
            "hook": lambda x: _path_convert(self.sync_dir, f"run-{self.run_id}.wandb"),
        }
        self.sync_symlink_latest: Any = {
            "value": "latest-run",
            "validator": lambda x: isinstance(x, str),
            "hook": lambda x: _path_convert(self.wandb_dir, x),
        }
        self.system_sample: Any = {
            "value": 15,
            "validator": lambda x: isinstance(x, int),
        }
        self.system_sample_seconds: Any = {
            "value": 2,
            "validator": lambda x: isinstance(x, int),
        }
        self.tmp_dir: Any = {
            "value": "tmp",
            "validator": lambda x: isinstance(x, str),
            "hook": lambda x: (
                _path_convert(self.wandb_dir, f"{self.run_mode}-{self.timespec}-{self.run_id}", x)
                or tempfile.gettempdir()
            ),
        }
        self.username: Any = {
            "validator": lambda x: isinstance(x, str),
        }

        # fixme: debug
        self.lol_id: Any = {
            "value": "abc123",
            "preprocessor": lambda x: str(x),
            "validator": lambda x: isinstance(x, str),
            "hook": lambda x: self._join_with_base_url(x),
            "is_policy": True,
        }

        # re-init attributes as Property objects. These are defaults, using Source.BASE
        for key, specs in self.__dict__.items():
            if isinstance(specs, dict):
                object.__setattr__(
                    self,
                    key,
                    Property(
                        name=key,
                        **specs,
                        # todo: double-check this logic:
                        source=Source.ARGS if specs.get("is_policy", False) else Source.BASE
                    ),
                )

        # update overridden defaults from kwargs
        unexpected_arguments = []
        for k, v in kwargs.items():
            if k in self.__dict__:
                self.update({k: v}, source=Source.SETTINGS)
            else:
                unexpected_arguments.append(k)
        # allow only explicitly defined arguments
        if unexpected_arguments:
            raise TypeError(f"Got unexpected arguments: {unexpected_arguments}")

        # setup private attributes
        object.__setattr__(self, "_Settings_start_datetime", None)
        object.__setattr__(self, "_Settings_start_time", None)

        if os.environ.get(wandb.env.DIR) is None:
            self.root_dir = os.path.abspath(os.getcwd())

        # done with init, use self.update() to update attributes from now on
        self.__initialized = True

        # freeze settings to prevent accidental changes
        # self.freeze()

    def __repr__(self):
        # return f"<Settings {[{a: p} for a, p in self.__dict__.items()]}>"
        return f"<Settings {self.__dict__}>"

    # attribute access methods
    if not TYPE_CHECKING:  # this a hack to make mypy happy
        @no_type_check  # another way to do this
        def __getattribute__(self, name: str) -> Any:
            """Expose attribute.value if attribute is a Property."""
            item = object.__getattribute__(self, name)
            if isinstance(item, Property):
                return item.value
            return item

    def __setattr__(self, key: str, value: Any) -> None:
        if "_Settings__initialized" in self.__dict__ and self.__initialized:
            raise TypeError("Please use update() to update attribute values")
        object.__setattr__(self, key, value)

    def update(
        self,
        settings: Optional[Dict[str, Any]] = None,
        source: int = Source.OVERRIDE,
        **kwargs: Any,
    ) -> None:
        """Update individual settings using the Property.update() method."""
        if "_Settings__frozen" in self.__dict__ and self.__frozen:
            raise TypeError(f"Settings object is frozen")
        if TYPE_CHECKING:
            _source = cast(Optional[int], source)
        # add kwargs to settings
        settings = settings or dict()
        # explicit kwargs take precedence over settings
        settings = {**settings, **kwargs}
        for key, value in settings.items():
            # only allow updating known Properties
            if key not in self.__dict__ or not isinstance(self.__dict__[key], Property):
                raise KeyError(f"Unknown setting: {key}")
        # only if all keys are valid, update them
        for key, value in settings.items():
            self.__dict__[key].update(value, source)

    def freeze(self) -> None:
        object.__setattr__(self, "_Settings__frozen", True)

    def unfreeze(self) -> None:
        object.__setattr__(self, "_Settings__frozen", False)

    def is_frozen(self) -> bool:
        return self.__frozen

    def make_static(self) -> Dict[str, Any]:
        """Generate a static, serializable version of the settings."""
        # get attributes that are instances of the Property class:
        attributes = {k: v.value for k, v in self.__dict__.items() if isinstance(v, Property)}
        # add @property-based settings:
        properties = {
            property_name: object.__getattribute__(self, property_name)
            for property_name, obj in self.__class__.__dict__.items()
            if isinstance(obj, property)
        }
        return {**attributes, **properties}

    # apply settings from different sources
    # TODO(dd): think about doing all that at init time
    @staticmethod
    def _load_config_file(file_name: str, section: str = "default") -> dict:
        parser = configparser.ConfigParser()
        parser.add_section(section)
        parser.read(file_name)
        config: Dict[str, Any] = dict()
        for k in parser[section]:
            config[k] = parser[section][k]
            # TODO (cvp): we didn't do this in the old cli, but it seems necessary
            if k == "ignore_globs":
                config[k] = config[k].split(",")
        return config

    def apply_config_files(self, _logger: Optional[_EarlyLogger] = None) -> None:
        # TODO(jhr): permit setting of config in system and workspace
        if self.settings_system is not None:
            if _logger is not None:
                _logger.info(f"Loading settings from {self.settings_system}")
            self.update(
                self._load_config_file(self.settings_system),
                source=Source.SYSTEM,
            )
        if self.settings_workspace is not None:
            if _logger is not None:
                _logger.info(f"Loading settings from {self.settings_workspace}")
            self.update(
                self._load_config_file(self.settings_workspace),
                source=Source.WORKSPACE,
            )

    def apply_env_vars(
        self,
        environ: Mapping[str, Any],
       _logger: Optional[_EarlyLogger] = None,
    ) -> None:
        env_prefix: str = "WANDB_"
        special_env_var_names = {
            "WANDB_DEBUG_LOG": "_debug_log",
            "WANDB_REQUIRE_SERVICE": "_require_service",
            "WANDB_SERVICE_TRANSPORT": "_service_transport",
            "WANDB_DIR": "root_dir",
            "WANDB_NAME": "run_name",
            "WANDB_NOTES": "run_notes",
            "WANDB_TAGS": "run_tags",
            "WANDB_JOB_TYPE": "run_job_type",
        }
        env = dict()
        for setting, value in environ.items():
            if not setting.startswith(env_prefix):
                continue

            if setting in special_env_var_names:
                key = special_env_var_names[setting]
            else:
                # otherwise, strip the prefix and convert to lowercase
                key = setting[len(env_prefix):].lower()

            if key in self.__dict__:
                if key in ("ignore_globs", "run_tags"):
                    value = value.split(",")
                env[key] = value
            elif _logger is not None:
                _logger.warning(f"Unknown environment variable: {setting}")

        if _logger is not None:
            _logger.info(
                f"Loading settings from environment variables: {_redact_dict(env)}"
            )

        self.update(env, source=Source.ENV)

    def infer_settings_from_environment(
        self,
        _logger: Optional[_EarlyLogger] = None
    ) -> None:
        """Modify settings based on environment (for runs and cli)."""

        settings: Dict[str, Union[bool, str, Sequence]] = dict()
        # disable symlinks if on windows (requires admin or developer setup)
        settings["symlink"] = True
        if self._windows:
            settings["symlink"] = False

        # TODO(jhr): this needs to be moved last in setting up settings ?
        #  (dd): loading order does not matter as long as source is set correctly

        # For code saving, only allow env var override if value from server is true, or
        # if no preference was specified.
        if (
            (self.save_code is True or self.save_code is None)
            and os.getenv(wandb.env.SAVE_CODE) is not None
            or os.getenv(wandb.env.DISABLE_CODE) is not None
        ):
            settings["save_code"] = wandb.env.should_save_code()

        settings["disable_git"] = wandb.env.disable_git()

        # Attempt to get notebook information if not already set by the user
        if self._jupyter and (self.notebook_name is None or self.notebook_name == ""):
            meta = wandb.jupyter.notebook_metadata(self._silent)
            settings["_jupyter_path"] = meta.get("path")
            settings["_jupyter_name"] = meta.get("name")
            settings["_jupyter_root"] = meta.get("root")
        elif (
            self._jupyter
            and self.notebook_name is not None
            and os.path.exists(self.notebook_name)
        ):
            settings["_jupyter_path"] = self.notebook_name
            settings["_jupyter_name"] = self.notebook_name
            settings["_jupyter_root"] = os.getcwd()
        elif self._jupyter:
            wandb.termwarn(
                "WANDB_NOTEBOOK_NAME should be a path to a notebook file, "
                f"couldn't find {self.notebook_name}"
            )

        # host and username are populated by apply_env_vars if corresponding env
        # vars exist -- but if they don't, we'll fill them in here
        if self.host is None:
            settings["host"] = socket.gethostname()

        if self.username is None:
            try:
                settings["username"] = getpass.getuser()
            except KeyError:
                # getuser() could raise KeyError in restricted environments like
                # chroot jails or docker containers. Return user id in these cases.
                settings["username"] = str(os.getuid())

        settings["_executable"] = sys.executable

        settings["docker"] = wandb.env.get_docker(wandb.util.image_id_from_k8s())

        # TODO: we should use the cuda library to collect this
        if os.path.exists("/usr/local/cuda/version.txt"):
            with open("/usr/local/cuda/version.txt") as f:
                settings["_cuda"] = f.read().split(" ")[-1].strip()
        settings["_args"] = sys.argv[1:]
        settings["_os"] = platform.platform(aliased=True)
        settings["_python"] = platform.python_version()
        # hack to make sure we don't hang on windows
        if self._windows and self._except_exit is None:
            settings["_except_exit"] = True

        if _logger is not None:
            _logger.info(
                f"Inferring settings from compute environment: {_redact_dict(settings)}"
            )

        self.update(settings, source=Source.ENV)

    def infer_run_settings_from_environment(
        self,
        _logger: Optional[_EarlyLogger] = None,
    ) -> None:
        """Modify settings based on environment (for runs only)."""
        # If there's not already a program file, infer it now.
        settings: Dict[str, Union[bool, str, None]] = dict()
        program = self.program or _get_program()
        if program is not None:
            program_relpath = (
                    self.program_relpath
                    or _get_program_relpath_from_gitrepo(program, _logger=_logger)
            )
            settings["program_relpath"] = program_relpath
        else:
            program = "<python with no main file>"

        settings["program"] = program

        if _logger is not None:
            _logger.info(
                f"Inferring run settings from compute environment: {_redact_dict(settings)}"
            )

        self.update(settings, source=Source.ENV)

    def apply_setup(
        self,
        setup_settings: Dict[str, Any],
        _logger: Optional[_EarlyLogger] = None
    ) -> None:
        if _logger:
            _logger.info(
                f"Applying setup settings: {_redact_dict(setup_settings)}"
            )
        self.update(setup_settings, source=Source.SETUP)

    def apply_user(
        self,
        user_settings: Dict[str, Any],
        _logger: Optional[_EarlyLogger] = None
    ) -> None:
        if _logger:
            _logger.info(
                f"Applying user settings: {_redact_dict(user_settings)}"
            )
        self.update(user_settings, source=Source.USER)

    def apply_init(
        self,
        init_settings: Dict[str, Union[str, int, None]]
    ) -> None:
        # prevent setting project, entity if in sweep
        # TODO(jhr): these should be locked elements in the future
        if self.sweep_id:
            for key in ("project", "entity", "id"):
                val = init_settings.pop(key, None)
                if val:
                    wandb.termwarn(
                        f"Ignored wandb.init() arg {key} when running a sweep"
                    )
        if self.launch:
            for key in ("project", "entity", "id"):
                val = init_settings.pop(key, None)
                if val:
                    wandb.termwarn(
                        "Project, entity and id are ignored when running from wandb launch context. "
                        f"Ignored wandb.init() arg {key} when running running from launch"
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
        init_settings = {
            param_map.get(k, k): v
            for k, v in init_settings.items()
            if v is not None
        }
        # fun logic to convert the resume init arg
        if init_settings.get("resume"):
            if isinstance(init_settings["resume"], str):
                if init_settings["resume"] not in ("allow", "must", "never", "auto"):
                    if init_settings.get("run_id") is None:
                        #  TODO: deprecate or don't support
                        init_settings["run_id"] = init_settings["resume"]
                    init_settings["resume"] = "allow"
            elif init_settings["resume"] is True:
                init_settings["resume"] = "auto"

        # update settings
        self.update(init_settings, source=Source.INIT)

        # handle auto resume logic
        if self.resume == "auto":
            if os.path.exists(self.resume_fname):
                with open(self.resume_fname) as f:
                    resume_run_id = json.load(f)["run_id"]
                if self.run_id is None:
                    self.run_id = resume_run_id
                elif self.run_id != resume_run_id:
                    wandb.termwarn(
                        "Tried to auto resume run with "
                        f"id {resume_run_id} but id {self.run_id} is set."
                    )
        self.update({"run_id": self.run_id or generate_id()}, source=Source.INIT)
        # persist our run id in case of failure
        # check None for mypy
        if self.resume == "auto" and self.resume_fname is not None:
            wandb.util.mkdir_exists_ok(self.wandb_dir)
            with open(self.resume_fname, "w") as f:
                f.write(json.dumps({"run_id": self.run_id}))

    def apply_login(
        self,
        login_settings: Dict[str, Any],
        _logger: Optional[_EarlyLogger] = None
    ) -> None:
        param_map = dict(key="api_key", host="base_url", timeout="login_timeout")
        login_settings = {param_map.get(k, k): v for k, v in login_settings.items() if v is not None}
        if login_settings:
            if _logger:
                _logger.info(
                    f"Applying login settings: {_redact_dict(login_settings)}"
                )
            self.update(login_settings, source=Source.LOGIN)

    # computed properties
    @property
    def _console(self) -> SettingsConsole:
        convert_dict: Dict[str, SettingsConsole] = dict(
            off=SettingsConsole.OFF,
            wrap=SettingsConsole.WRAP,
            redirect=SettingsConsole.REDIRECT,
        )
        console: str = str(self.console)
        if console == "auto":
            if (
                    self._jupyter
                    or (self.start_method == "thread")
                    or self._require_service
                    or self._windows
            ):
                console = "wrap"
            else:
                console = "redirect"
        convert: SettingsConsole = convert_dict[console]
        return convert

    @property
    def _jupyter(self) -> bool:
        return str(_get_python_type()) != "python"

    @property
    def _kaggle(self) -> bool:
        is_kaggle = util._is_likely_kaggle()
        if TYPE_CHECKING:
            assert isinstance(is_kaggle, bool)
        return is_kaggle

    @property
    def _noop(self) -> bool:
        return self.mode == "disabled"

    @property
    def _offline(self) -> bool:
        if self.disabled or (self.mode in ("dryrun", "offline")):
            return True
        return False

    @property
    def _show_info(self) -> Optional[bool]:
        return self.show_info

    @property
    def _show_warnings(self) -> Optional[bool]:
        return self.show_warnings

    @property
    def _show_errors(self) -> Optional[bool]:
        return self.show_errors

    @property
    def _silent(self) -> Optional[bool]:
        return self.silent

    @property
    def _windows(self) -> bool:
        return platform.system() == "Windows"

    @property
    def is_local(self) -> bool:
        if self.base_url is not None:
            return self.base_url != "https://api.wandb.ai"
        return False

    @property
    def run_mode(self) -> str:
        return "offline-run" if self._offline else "run"

    @property
    def timespec(self) -> Optional[str]:
        if self._start_time and self._start_datetime:
            return datetime.strftime(
                self._start_datetime, "%Y%m%d_%H%M%S"
            )

    @property
    def wandb_dir(self) -> str:
        return get_wandb_dir(self.root_dir or "")
