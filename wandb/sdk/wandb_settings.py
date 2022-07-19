import configparser
from datetime import datetime
from distutils.util import strtobool
import enum
from functools import reduce
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
    Dict,
    FrozenSet,
    ItemsView,
    Iterable,
    Mapping,
    no_type_check,
    Optional,
    Sequence,
    Set,
    Tuple,
    Union,
)
from urllib.parse import quote, urlencode, urlparse, urlsplit

import wandb
from wandb import util
from wandb.apis.internal import Api
import wandb.env
from wandb.errors import UsageError
from wandb.sdk.wandb_config import Config
from wandb.sdk.wandb_setup import _EarlyLogger

from .lib import apikey
from .lib.git import GitRepo
from .lib.ipython import _get_python_type
from .lib.runid import generate_id

if sys.version_info >= (3, 8):
    from typing import get_args, get_origin, get_type_hints
elif sys.version_info >= (3, 7):
    from typing_extensions import get_args, get_origin, get_type_hints
else:

    def get_args(obj: Any) -> Optional[Any]:
        return obj.__args__ if hasattr(obj, "__args__") else None

    def get_origin(obj: Any) -> Optional[Any]:
        return obj.__origin__ if hasattr(obj, "__origin__") else None

    def get_type_hints(obj: Any) -> Dict[str, Any]:
        return dict(obj.__annotations__) if hasattr(obj, "__annotations__") else dict()


def _get_wandb_dir(root_dir: str) -> str:
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
        wandb.termwarn(
            f"Path {path} wasn't writable, using system temp directory.",
            repeat=False,
        )
        path = os.path.join(tempfile.gettempdir(), __stage_dir__ or ("wandb" + os.sep))

    return os.path.expanduser(path)


# todo: should either return bool or error out. fix once confident.
def _str_as_bool(val: Union[str, bool]) -> bool:
    """
    Parse a string as a bool.
    """
    if isinstance(val, bool):
        return val
    try:
        ret_val = bool(strtobool(str(val)))
        return ret_val
    except (AttributeError, ValueError):
        pass

    # todo: remove this and only raise error once we are confident.
    wandb.termwarn(
        f"Could not parse value {val} as a bool. ",
        repeat=False,
    )
    raise UsageError(f"Could not parse value {val} as a bool.")


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

        if __main__.__spec__ is None:
            return __main__.__file__
        # likely run as `python -m ...`
        return f"-m {__main__.__spec__.name}"
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
    BASE: int = 1  # todo: audit this
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
    RUN: int = 14


@enum.unique
class SettingsConsole(enum.IntEnum):
    OFF = 0
    WRAP = 1
    REDIRECT = 2
    WRAP_RAW = 3
    WRAP_EMU = 4


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

    # todo: this is a temporary measure to bypass validation of the settings
    #  whose validation was not previously enforced to make sure we don't brake anything.
    __strict_validate_settings = {
        "project",
        "start_method",
        "mode",
        "console",
        "problem",
        "anonymous",
        "strict",
        "silent",
        "show_info",
        "show_warnings",
        "show_errors",
        "base_url",
        "login_timeout",
    }

    def __init__(  # pylint: disable=unused-argument
        self,
        name: str,
        value: Optional[Any] = None,
        preprocessor: Union[Callable, Sequence[Callable], None] = None,
        # validators allow programming by contract
        validator: Union[Callable, Sequence[Callable], None] = None,
        # runtime converter (hook): properties can be e.g. tied to other properties
        hook: Union[Callable, Sequence[Callable], None] = None,
        # always apply hook even if value is None. can be used to replace @property's
        auto_hook: bool = False,
        is_policy: bool = False,
        frozen: bool = False,
        source: int = Source.BASE,
        **kwargs: Any,
    ):
        self.name = name
        self._preprocessor = preprocessor
        self._validator = validator
        self._hook = hook
        self._auto_hook = auto_hook
        self._is_policy = is_policy
        self._source = source

        # todo: this is a temporary measure to collect stats on failed preprocessing and validation
        self.__failed_preprocessing: bool = False
        self.__failed_validation: bool = False

        # preprocess and validate value
        self._value = self._validate(self._preprocess(value))

        self.__frozen = frozen

    @property
    def value(self) -> Any:
        """Apply the runtime modifier(s) (if any) and return the value."""
        _value = self._value
        if (_value is not None or self._auto_hook) and self._hook is not None:
            _hook = [self._hook] if callable(self._hook) else self._hook
            for h in _hook:
                _value = h(_value)
        return _value

    @property
    def is_policy(self) -> bool:
        return self._is_policy

    @property
    def source(self) -> int:
        return self._source

    def _preprocess(self, value: Any) -> Any:
        if value is not None and self._preprocessor is not None:
            _preprocessor = (
                [self._preprocessor]
                if callable(self._preprocessor)
                else self._preprocessor
            )
            for p in _preprocessor:
                try:
                    value = p(value)
                except (UsageError, ValueError):
                    wandb.termwarn(
                        f"Unable to preprocess value for property {self.name}: {value}. "
                        "This will raise an error in the future.",
                        repeat=False,
                    )
                    self.__failed_preprocessing = True
                    break
        return value

    def _validate(self, value: Any) -> Any:
        self.__failed_validation = False  # todo: this is a temporary measure
        if value is not None and self._validator is not None:
            _validator = (
                [self._validator] if callable(self._validator) else self._validator
            )
            for v in _validator:
                if not v(value):
                    # todo: this is a temporary measure to bypass validation of certain settings.
                    #  remove this once we are confident
                    if self.name in self.__strict_validate_settings:
                        raise ValueError(
                            f"Invalid value for property {self.name}: {value}"
                        )
                    else:
                        wandb.termwarn(
                            f"Invalid value for property {self.name}: {value}. "
                            "This will raise an error in the future.",
                            repeat=False,
                        )
                        self.__failed_validation = True
                        break
        return value

    def update(self, value: Any, source: int = Source.OVERRIDE) -> None:
        """Update the value of the property."""
        if self.__frozen:
            raise TypeError("Property object is frozen")
        # - always update value if source == Source.OVERRIDE
        # - if not previously overridden:
        #   - update value if source is lower than or equal to current source and property is policy
        #   - update value if source is higher than or equal to current source and property is not policy
        if (
            (source == Source.OVERRIDE)
            or (
                self._is_policy
                and self._source != Source.OVERRIDE
                and source <= self._source
            )
            or (
                not self._is_policy
                and self._source != Source.OVERRIDE
                and source >= self._source
            )
        ):
            # self.__dict__["_value"] = self._validate(self._preprocess(value))
            self._value = self._validate(self._preprocess(value))
            self._source = source

    def __setattr__(self, key: str, value: Any) -> None:
        if "_Property__frozen" in self.__dict__ and self.__frozen:
            raise TypeError(f"Property object {self.name} is frozen")
        if key == "value":
            raise AttributeError("Use update() to update property value")
        self.__dict__[key] = value

    def __str__(self) -> str:
        return f"'{self.value}'" if isinstance(self.value, str) else f"{self.value}"

    def __repr__(self) -> str:
        return (
            f"<Property {self.name}: value={self.value} "
            f"_value={self._value} source={self._source} is_policy={self._is_policy}>"
        )
        # return f"<Property {self.name}: value={self.value}>"
        # return self.__dict__.__repr__()


class Settings:
    """
    Settings for the wandb client.
    """

    # settings are declared as class attributes for static type checking purposes
    # and to help with IDE autocomplete.
    _args: Sequence[str]
    _cli_only_mode: bool  # Avoid running any code specific for runs
    _colab: bool
    _config_dict: Config
    _console: SettingsConsole
    _cuda: str
    _disable_meta: bool
    _disable_stats: bool
    _disable_viewer: bool  # Prevent early viewer query
    _except_exit: bool
    _executable: str
    _internal_check_process: Union[int, float]
    _internal_queue_timeout: Union[int, float]
    _jupyter: bool
    _jupyter_name: str
    _jupyter_path: str
    _jupyter_root: str
    _kaggle: bool
    _live_policy_rate_limit: int
    _live_policy_wait_time: int
    _noop: bool
    _offline: bool
    _os: str
    _platform: str
    _python: str
    _require_service: str
    _runqueue_item_id: str
    _save_requirements: bool
    _service_transport: str
    _start_datetime: datetime
    _start_time: float
    _stats_pid: int  # (internal) base pid for system stats
    _stats_sample_rate_seconds: float
    _stats_samples_to_average: int
    _tmp_code_dir: str
    _tracelog: str
    _unsaved_keys: Sequence[str]
    _windows: bool
    allow_val_change: bool
    anonymous: str
    api_key: str
    base_url: str  # The base url for the wandb api
    code_dir: str
    config_paths: Sequence[str]
    console: str
    deployment: str
    disable_code: bool
    disable_git: bool
    disable_hints: bool
    disabled: bool  # Alias for mode=dryrun, not supported yet
    docker: str
    email: str
    enable_job_creation: bool
    entity: str
    files_dir: str
    force: bool
    git_commit: str
    git_remote: str
    git_remote_url: str
    git_root: str
    heartbeat_seconds: int
    host: str
    ignore_globs: Tuple[str]
    init_timeout: int
    is_local: bool
    label_disable: bool
    launch: bool
    launch_config_path: str
    log_dir: str
    log_internal: str
    log_symlink_internal: str
    log_symlink_user: str
    log_user: str
    login_timeout: float
    magic: Union[str, bool, dict]
    mode: str
    notebook_name: str
    problem: str
    program: str
    program_relpath: str
    project: str
    project_url: str
    quiet: bool
    reinit: bool
    relogin: bool
    resume: Union[str, int, bool]
    resume_fname: str
    resumed: bool  # indication from the server about the state of the run (different from resume - user provided flag)
    root_dir: str
    run_group: str
    run_id: str
    run_job_type: str
    run_mode: str
    run_name: str
    run_notes: str
    run_tags: Tuple[str]
    run_url: str
    sagemaker_disable: bool
    save_code: bool
    settings_system: str
    settings_workspace: str
    show_colors: bool
    show_emoji: bool
    show_errors: bool
    show_info: bool
    show_warnings: bool
    silent: bool
    start_method: str
    strict: bool
    summary_errors: int
    summary_warnings: int
    sweep_id: str
    sweep_param_path: str
    sweep_url: str
    symlink: bool
    sync_dir: str
    sync_file: str
    sync_symlink_latest: str
    system_sample: int
    system_sample_seconds: int
    timespec: str
    tmp_dir: str
    username: str
    wandb_dir: str
    table_raise_on_max_row_limit_exceeded: bool

    def _default_props(self) -> Dict[str, Dict[str, Any]]:
        """
        Helper method that is used in `__init__` together with the class attributes
        to initialize instance attributes (individual settings) as Property objects.
        Note that key names must be the same as the class attribute names.
        """
        return dict(
            _disable_meta={"preprocessor": _str_as_bool},
            _disable_stats={"preprocessor": _str_as_bool},
            _disable_viewer={"preprocessor": _str_as_bool},
            _colab={
                "hook": lambda _: "google.colab" in sys.modules,
                "auto_hook": True,
            },
            _console={"hook": lambda _: self._convert_console(), "auto_hook": True},
            _internal_check_process={"value": 8},
            _internal_queue_timeout={"value": 2},
            _jupyter={
                "hook": lambda _: str(_get_python_type()) != "python",
                "auto_hook": True,
            },
            _kaggle={"hook": lambda _: util._is_likely_kaggle(), "auto_hook": True},
            _noop={"hook": lambda _: self.mode == "disabled", "auto_hook": True},
            _offline={
                "hook": (
                    lambda _: True
                    if self.disabled or (self.mode in ("dryrun", "offline"))
                    else False
                ),
                "auto_hook": True,
            },
            _platform={"value": util.get_platform_name()},
            _save_requirements={"value": True, "preprocessor": _str_as_bool},
            _stats_sample_rate_seconds={"value": 2.0},
            _stats_samples_to_average={"value": 15},
            _tmp_code_dir={
                "value": "code",
                "hook": lambda x: self._path_convert(self.tmp_dir, x),
            },
            _windows={
                "hook": lambda _: platform.system() == "Windows",
                "auto_hook": True,
            },
            anonymous={"validator": self._validate_anonymous},
            api_key={"validator": self._validate_api_key},
            base_url={
                "value": "https://api.wandb.ai",
                "preprocessor": lambda x: str(x).strip().rstrip("/"),
                "validator": self._validate_base_url,
            },
            console={"value": "auto", "validator": self._validate_console},
            deployment={
                "hook": lambda _: "local" if self.is_local else "cloud",
                "auto_hook": True,
            },
            disable_code={"preprocessor": _str_as_bool},
            disable_hints={"preprocessor": _str_as_bool},
            disable_git={"preprocessor": _str_as_bool},
            disabled={"value": False, "preprocessor": _str_as_bool},
            enable_job_creation={"preprocessor": _str_as_bool},
            files_dir={
                "value": "files",
                "hook": lambda x: self._path_convert(
                    self.wandb_dir, f"{self.run_mode}-{self.timespec}-{self.run_id}", x
                ),
            },
            force={"preprocessor": _str_as_bool},
            git_remote={"value": "origin"},
            heartbeat_seconds={"value": 30},
            ignore_globs={
                "value": tuple(),
                "preprocessor": lambda x: tuple(x) if not isinstance(x, tuple) else x,
            },
            init_timeout={"value": 30, "preprocessor": lambda x: int(x)},
            is_local={
                "hook": (
                    lambda _: self.base_url != "https://api.wandb.ai"
                    if self.base_url is not None
                    else False
                ),
                "auto_hook": True,
            },
            label_disable={"preprocessor": _str_as_bool},
            launch={"preprocessor": _str_as_bool},
            log_dir={
                "value": "logs",
                "hook": lambda x: self._path_convert(
                    self.wandb_dir, f"{self.run_mode}-{self.timespec}-{self.run_id}", x
                ),
            },
            log_internal={
                "value": "debug-internal.log",
                "hook": lambda x: self._path_convert(self.log_dir, x),
            },
            log_symlink_internal={
                "value": "debug-internal.log",
                "hook": lambda x: self._path_convert(self.wandb_dir, x),
            },
            log_symlink_user={
                "value": "debug.log",
                "hook": lambda x: self._path_convert(self.wandb_dir, x),
            },
            log_user={
                "value": "debug.log",
                "hook": lambda x: self._path_convert(self.log_dir, x),
            },
            login_timeout={"preprocessor": lambda x: float(x)},
            mode={"value": "online", "validator": self._validate_mode},
            problem={"value": "fatal", "validator": self._validate_problem},
            project={"validator": self._validate_project},
            project_url={"hook": lambda _: self._project_url(), "auto_hook": True},
            quiet={"preprocessor": _str_as_bool},
            reinit={"preprocessor": _str_as_bool},
            relogin={"preprocessor": _str_as_bool},
            resume_fname={
                "value": "wandb-resume.json",
                "hook": lambda x: self._path_convert(self.wandb_dir, x),
            },
            resumed={"value": "False", "preprocessor": _str_as_bool},
            run_mode={
                "hook": lambda _: "offline-run" if self._offline else "run",
                "auto_hook": True,
            },
            run_tags={
                "preprocessor": lambda x: tuple(x) if not isinstance(x, tuple) else x,
            },
            run_url={"hook": lambda _: self._run_url(), "auto_hook": True},
            sagemaker_disable={"preprocessor": _str_as_bool},
            save_code={"preprocessor": _str_as_bool},
            settings_system={
                "value": os.path.join("~", ".config", "wandb", "settings"),
                "hook": lambda x: self._path_convert(x),
            },
            settings_workspace={
                "value": "settings",
                "hook": lambda x: self._path_convert(self.wandb_dir, x),
            },
            show_colors={"preprocessor": _str_as_bool},
            show_emoji={"preprocessor": _str_as_bool},
            show_errors={"value": "True", "preprocessor": _str_as_bool},
            show_info={"value": "True", "preprocessor": _str_as_bool},
            show_warnings={"value": "True", "preprocessor": _str_as_bool},
            silent={"value": "False", "preprocessor": _str_as_bool},
            start_method={"validator": self._validate_start_method},
            strict={"preprocessor": _str_as_bool},
            summary_warnings={
                "value": 5,
                "preprocessor": lambda x: int(x),
                "is_policy": True,
            },
            sweep_url={"hook": lambda _: self._sweep_url(), "auto_hook": True},
            symlink={"preprocessor": _str_as_bool},
            sync_dir={
                "hook": [
                    lambda _: self._path_convert(
                        self.wandb_dir, f"{self.run_mode}-{self.timespec}-{self.run_id}"
                    )
                ],
                "auto_hook": True,
            },
            sync_file={
                "hook": lambda _: self._path_convert(
                    self.sync_dir, f"run-{self.run_id}.wandb"
                ),
                "auto_hook": True,
            },
            sync_symlink_latest={
                "value": "latest-run",
                "hook": lambda x: self._path_convert(self.wandb_dir, x),
            },
            system_sample={"value": 15},
            system_sample_seconds={"value": 2},
            table_raise_on_max_row_limit_exceeded={
                "value": False,
                "preprocessor": _str_as_bool,
            },
            timespec={
                "hook": (
                    lambda _: (
                        datetime.strftime(self._start_datetime, "%Y%m%d_%H%M%S")
                        if self._start_datetime
                        else None
                    )
                ),
                "auto_hook": True,
            },
            tmp_dir={
                "value": "tmp",
                "hook": lambda x: (
                    self._path_convert(
                        self.wandb_dir,
                        f"{self.run_mode}-{self.timespec}-{self.run_id}",
                        x,
                    )
                    or tempfile.gettempdir()
                ),
            },
            wandb_dir={
                "hook": lambda _: _get_wandb_dir(self.root_dir or ""),
                "auto_hook": True,
            },
        )

    # helper methods for validating values
    @staticmethod
    def _validator_factory(hint: Any) -> Callable[[Any], bool]:
        """
        Factory for type validators, given a type hint:
        Convert the type hint of a setting into a function
        that checks if the argument is of the correct type
        """
        origin, args = get_origin(hint), get_args(hint)

        def helper(x: Any) -> bool:
            if origin is None:
                return isinstance(x, hint)
            elif origin is Union:
                return isinstance(x, args) if args is not None else True
            else:
                return (
                    isinstance(x, origin) and all(isinstance(y, args) for y in x)
                    if args is not None
                    else isinstance(x, origin)
                )

        return helper

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
                raise UsageError(
                    f'Invalid project name "{value}": exceeded 128 characters'
                )
            invalid_chars = {char for char in invalid_chars_list if char in value}
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
            raise UsageError(
                f"Settings field `start_method`: '{value}' not in {available_methods}"
            )
        return True

    @staticmethod
    def _validate_console(value: str) -> bool:
        # choices = {"auto", "redirect", "off", "file", "iowrap", "notebook"}
        choices: Set[str] = {
            "auto",
            "redirect",
            "off",
            "wrap",
            # internal console states
            "wrap_emu",
            "wrap_raw",
        }
        if value not in choices:
            # do not advertise internal console states
            choices -= {"wrap_emu", "wrap_raw"}
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
    def _validate_api_key(value: str) -> bool:
        if len(value) > len(value.strip()):
            raise UsageError("API key cannot start or end with whitespace")

        # if value.startswith("local") and not self.is_local:
        #     raise UsageError(
        #         "Attempting to use a local API key to connect to https://api.wandb.ai"
        #     )
        # todo: move here the logic from sdk/lib/apikey.py

        return True

    @staticmethod
    def _validate_base_url(value: Optional[str]) -> bool:
        """
        Validate the base url of the wandb server.

        param value: URL to validate

        Based on the Django URLValidator, but with a few additional checks.

        Copyright (c) Django Software Foundation and individual contributors.
        All rights reserved.

        Redistribution and use in source and binary forms, with or without modification,
        are permitted provided that the following conditions are met:

            1. Redistributions of source code must retain the above copyright notice,
               this list of conditions and the following disclaimer.

            2. Redistributions in binary form must reproduce the above copyright
               notice, this list of conditions and the following disclaimer in the
               documentation and/or other materials provided with the distribution.

            3. Neither the name of Django nor the names of its contributors may be used
               to endorse or promote products derived from this software without
               specific prior written permission.

        THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
        ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
        WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
        DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR
        ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
        (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
        LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON
        ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
        (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
        SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
        """
        if value is None:
            return True

        ul = "\u00a1-\uffff"  # Unicode letters range (must not be a raw string).

        # IP patterns
        ipv4_re = (
            r"(?:0|25[0-5]|2[0-4][0-9]|1[0-9]?[0-9]?|[1-9][0-9]?)"
            r"(?:\.(?:0|25[0-5]|2[0-4][0-9]|1[0-9]?[0-9]?|[1-9][0-9]?)){3}"
        )
        ipv6_re = r"\[[0-9a-f:.]+\]"  # (simple regex, validated later)

        # Host patterns
        hostname_re = (
            r"[a-z" + ul + r"0-9](?:[a-z" + ul + r"0-9-]{0,61}[a-z" + ul + r"0-9])?"
        )
        # Max length for domain name labels is 63 characters per RFC 1034 sec. 3.1
        domain_re = r"(?:\.(?!-)[a-z" + ul + r"0-9-]{1,63}(?<!-))*"
        tld_re = (
            r"\."  # dot
            r"(?!-)"  # can't start with a dash
            r"(?:[a-z" + ul + "-]{2,63}"  # domain label
            r"|xn--[a-z0-9]{1,59})"  # or punycode label
            r"(?<!-)"  # can't end with a dash
            r"\.?"  # may have a trailing dot
        )
        # host_re = "(" + hostname_re + domain_re + tld_re + "|localhost)"
        # todo?: allow hostname to be just a hostname (no tld)?
        host_re = "(" + hostname_re + domain_re + f"({tld_re})?" + "|localhost)"

        regex = re.compile(
            r"^(?:[a-z0-9.+-]*)://"  # scheme is validated separately
            r"(?:[^\s:@/]+(?::[^\s:@/]*)?@)?"  # user:pass authentication
            r"(?:" + ipv4_re + "|" + ipv6_re + "|" + host_re + ")"
            r"(?::[0-9]{1,5})?"  # port
            r"(?:[/?#][^\s]*)?"  # resource path
            r"\Z",
            re.IGNORECASE,
        )
        schemes = {"http", "https"}
        unsafe_chars = frozenset("\t\r\n")

        scheme = value.split("://")[0].lower()
        split_url = urlsplit(value)
        parsed_url = urlparse(value)

        if re.match(r".*wandb\.ai[^\.]*$", value) and "api." not in value:
            # user might guess app.wandb.ai or wandb.ai is the default cloud server
            raise UsageError(
                f"{value} is not a valid server address, did you mean https://api.wandb.ai?"
            )
        elif re.match(r".*wandb\.ai[^\.]*$", value) and scheme != "https":
            raise UsageError("http is not secure, please use https://api.wandb.ai")
        elif parsed_url.netloc == "":
            raise UsageError(f"Invalid URL: {value}")
        elif unsafe_chars.intersection(value):
            raise UsageError("URL cannot contain unsafe characters")
        elif scheme not in schemes:
            raise UsageError("URL must start with `http(s)://`")
        elif not regex.search(value):
            raise UsageError(f"{value} is not a valid server address")
        elif split_url.hostname is None or len(split_url.hostname) > 253:
            raise UsageError("hostname is invalid")

        return True

    # other helper methods
    @staticmethod
    def _path_convert(*args: str) -> str:
        """
        Join path and apply os.path.expanduser to it.
        """
        return os.path.expanduser(os.path.join(*args))

    def _convert_console(self) -> SettingsConsole:
        convert_dict: Dict[str, SettingsConsole] = dict(
            off=SettingsConsole.OFF,
            wrap=SettingsConsole.WRAP,
            wrap_raw=SettingsConsole.WRAP_RAW,
            wrap_emu=SettingsConsole.WRAP_EMU,
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

    def _get_url_query_string(self) -> str:
        # TODO(settings) use `wandb_setting` (if self.anonymous != "true":)
        if Api().settings().get("anonymous") != "true":
            return ""

        api_key = apikey.api_key(settings=self)

        return f"?{urlencode({'apiKey': api_key})}"

    def _project_url_base(self) -> str:
        if not all([self.entity, self.project]):
            return ""

        app_url = wandb.util.app_url(self.base_url)
        return f"{app_url}/{quote(self.entity)}/{quote(self.project)}"

    def _project_url(self) -> str:
        project_url = self._project_url_base()
        if not project_url:
            return ""

        query = self._get_url_query_string()

        return f"{project_url}{query}"

    def _run_url(self) -> str:
        """
        Return the run url.
        """
        project_url = self._project_url_base()
        if not all([project_url, self.run_id]):
            return ""

        query = self._get_url_query_string()
        return f"{project_url}/runs/{quote(self.run_id)}{query}"

    def _set_run_start_time(self, source: int = Source.BASE) -> None:
        """
        Set the time stamps for the settings.
        Called once the run is initialized.
        """
        time_stamp: float = time.time()
        datetime_now: datetime = datetime.fromtimestamp(time_stamp)
        object.__setattr__(self, "_Settings_start_datetime", datetime_now)
        object.__setattr__(self, "_Settings_start_time", time_stamp)
        self.update(
            _start_datetime=datetime_now,
            _start_time=time_stamp,
            source=source,
        )

    def _sweep_url(self) -> str:
        """
        Return the sweep url.
        """
        project_url = self._project_url_base()
        if not all([project_url, self.sweep_id]):
            return ""

        query = self._get_url_query_string()
        return f"{project_url}/sweeps/{quote(self.sweep_id)}{query}"

    def __init__(self, **kwargs: Any) -> None:
        self.__frozen: bool = False
        self.__initialized: bool = False

        # todo: this is collect telemetry on validation errors and unexpected args
        # values are stored as strings to avoid potential json serialization errors down the line
        self.__preprocessing_warnings: Dict[str, str] = dict()
        self.__validation_warnings: Dict[str, str] = dict()
        self.__unexpected_args: Set[str] = set()

        # Set default settings values
        # We start off with the class attributes and `default_props`' dicts
        # and then create Property objects.
        # Once initialized, attributes are to only be updated using the `update` method
        default_props = self._default_props()

        # Init instance attributes as Property objects.
        # Type hints of class attributes are used to generate a type validator function
        # for runtime checks for each attribute.
        # These are defaults, using Source.BASE for non-policy attributes and Source.RUN for policies.
        for prop, type_hint in get_type_hints(Settings).items():
            validators = [self._validator_factory(type_hint)]

            if prop in default_props:
                validator = default_props[prop].pop("validator", [])
                # Property validator could be either Callable or Sequence[Callable]
                if callable(validator):
                    validators.append(validator)
                elif isinstance(validator, Sequence):
                    validators.extend(list(validator))
                object.__setattr__(
                    self,
                    prop,
                    Property(
                        name=prop,
                        **default_props[prop],
                        validator=validators,
                        # todo: double-check this logic:
                        source=Source.RUN
                        if default_props[prop].get("is_policy", False)
                        else Source.BASE,
                    ),
                )
            else:
                object.__setattr__(
                    self,
                    prop,
                    Property(
                        name=prop,
                        validator=validators,
                        source=Source.BASE,
                    ),
                )

            # todo: this is to collect stats on preprocessing and validation errors
            if self.__dict__[prop].__dict__["_Property__failed_preprocessing"]:
                self.__preprocessing_warnings[prop] = str(self.__dict__[prop]._value)
            if self.__dict__[prop].__dict__["_Property__failed_validation"]:
                self.__validation_warnings[prop] = str(self.__dict__[prop]._value)

        # update overridden defaults from kwargs
        unexpected_arguments = [k for k in kwargs.keys() if k not in self.__dict__]
        # allow only explicitly defined arguments
        if unexpected_arguments:

            # todo: remove this and raise error instead once we are confident
            self.__unexpected_args.update(unexpected_arguments)
            wandb.termwarn(
                f"Ignoring unexpected arguments: {unexpected_arguments}. "
                "This will raise an error in the future."
            )
            for k in unexpected_arguments:
                kwargs.pop(k)

            # raise TypeError(f"Got unexpected arguments: {unexpected_arguments}")

        for k, v in kwargs.items():
            # todo: double-check this logic:
            source = Source.RUN if self.__dict__[k].is_policy else Source.BASE
            self.update({k: v}, source=source)

        # setup private attributes
        object.__setattr__(self, "_Settings_start_datetime", None)
        object.__setattr__(self, "_Settings_start_time", None)

        if os.environ.get(wandb.env.DIR) is None:
            # todo: double-check source, shouldn't it be Source.ENV?
            self.update({"root_dir": os.path.abspath(os.getcwd())}, source=Source.BASE)

        # done with init, use self.update() to update attributes from now on
        self.__initialized = True

        # todo? freeze settings to prevent accidental changes
        # self.freeze()

    def __str__(self) -> str:
        # get attributes that are instances of the Property class:
        representation = {
            k: v.value for k, v in self.__dict__.items() if isinstance(v, Property)
        }
        return f"<Settings {_redact_dict(representation)}>"

    def __repr__(self) -> str:
        # private attributes
        private = {k: v for k, v in self.__dict__.items() if k.startswith("_Settings")}
        # get attributes that are instances of the Property class:
        attributes = {
            k: f"<Property value={v.value} source={v.source}>"
            for k, v in self.__dict__.items()
            if isinstance(v, Property)
        }
        representation = {**private, **attributes}
        return f"<Settings {representation}>"

    def __copy__(self) -> "Settings":
        """
        Ensure that a copy of the settings object is a truly deep copy

        Note that the copied object will not be frozen  todo? why is this needed?
        """
        # get attributes that are instances of the Property class:
        attributes = {k: v for k, v in self.__dict__.items() if isinstance(v, Property)}
        new = Settings()
        for k, v in attributes.items():
            # make sure to use the raw property value (v._value),
            # not the potential result of runtime hooks applied to it (v.value)
            new.update({k: v._value}, source=v.source)
        new.unfreeze()

        return new

    def __deepcopy__(self, memo: dict) -> "Settings":
        return self.__copy__()

    # attribute access methods
    @no_type_check  # this is a hack to make mypy happy
    def __getattribute__(self, name: str) -> Any:
        """Expose attribute.value if attribute is a Property."""
        item = object.__getattribute__(self, name)
        if isinstance(item, Property):
            return item.value
        return item

    def __setattr__(self, key: str, value: Any) -> None:
        if "_Settings__initialized" in self.__dict__ and self.__initialized:
            raise TypeError(f"Please use update() to update attribute `{key}` value")
        object.__setattr__(self, key, value)

    def __iter__(self) -> Iterable:
        return iter(self.make_static())

    def copy(self) -> "Settings":
        return self.__copy__()

    # implement the Mapping interface
    def keys(self) -> Iterable[str]:
        return self.make_static().keys()

    @no_type_check  # this is a hack to make mypy happy
    def __getitem__(self, name: str) -> Any:
        """Expose attribute.value if attribute is a Property."""
        item = object.__getattribute__(self, name)
        if isinstance(item, Property):
            return item.value
        return item

    def update(
        self,
        settings: Optional[Union[Dict[str, Any], "Settings"]] = None,
        source: int = Source.OVERRIDE,
        **kwargs: Any,
    ) -> None:
        """Update individual settings using the Property.update() method."""
        if "_Settings__frozen" in self.__dict__ and self.__frozen:
            raise TypeError("Settings object is frozen")

        if isinstance(settings, Settings):
            # If a Settings object is passed, detect the settings that differ
            # from defaults, collect them into a dict, and apply them using `source`.
            # This comes up in `wandb.init(settings=wandb.Settings(...))` and
            # seems like the behavior that the user would expect when calling init that way.
            defaults = Settings()
            settings_dict = dict()
            for k, v in settings.__dict__.items():
                if isinstance(v, Property):
                    if v._value != defaults.__dict__[k]._value:
                        settings_dict[k] = v._value
            # todo: store warnings from the passed Settings object, if any,
            #  to collect telemetry on validation errors and unexpected args.
            #  remove this once strict checking is enforced.
            for attr in (
                "_Settings__unexpected_args",
                "_Settings__preprocessing_warnings",
                "_Settings__validation_warnings",
            ):
                getattr(self, attr).update(getattr(settings, attr))
            # replace with the generated dict
            settings = settings_dict

        # add kwargs to settings
        settings = settings or dict()
        # explicit kwargs take precedence over settings
        settings = {**settings, **kwargs}
        unknown_properties = []
        for key in settings.keys():
            # only allow updating known Properties
            if key not in self.__dict__ or not isinstance(self.__dict__[key], Property):
                unknown_properties.append(key)
        if unknown_properties:
            raise KeyError(f"Unknown settings: {unknown_properties}")
        # only if all keys are valid, update them
        for key, value in settings.items():
            self.__dict__[key].update(value, source)

            # todo: this is to collect stats on preprocessing and validation errors
            if self.__dict__[key].__dict__["_Property__failed_preprocessing"]:
                self.__preprocessing_warnings[key] = str(self.__dict__[key]._value)
            else:
                self.__preprocessing_warnings.pop(key, None)

            if self.__dict__[key].__dict__["_Property__failed_validation"]:
                self.__validation_warnings[key] = str(self.__dict__[key]._value)
            else:
                self.__validation_warnings.pop(key, None)

    def items(self) -> ItemsView[str, Any]:
        return self.make_static().items()

    def get(self, key: str, default: Any = None) -> Any:
        return self.make_static().get(key, default)

    def freeze(self) -> None:
        object.__setattr__(self, "_Settings__frozen", True)

    def unfreeze(self) -> None:
        object.__setattr__(self, "_Settings__frozen", False)

    def is_frozen(self) -> bool:
        return self.__frozen

    def make_static(self) -> Dict[str, Any]:
        """Generate a static, serializable version of the settings."""
        # get attributes that are instances of the Property class:
        attributes = {
            k: v.value for k, v in self.__dict__.items() if isinstance(v, Property)
        }
        return attributes

    # apply settings from different sources
    # TODO(dd): think about doing some|all of that at init
    def _apply_settings(
        self,
        settings: "Settings",
        _logger: Optional[_EarlyLogger] = None,
    ) -> None:
        """Apply settings from a Settings object."""
        if _logger is not None:
            _logger.info(f"Applying settings from {settings}")
        attributes = {
            k: v for k, v in settings.__dict__.items() if isinstance(v, Property)
        }
        for k, v in attributes.items():
            # note that only the same/higher priority settings are propagated
            self.update({k: v._value}, source=v.source)

        # todo: this is to pass on info on unexpected args in settings
        if settings.__dict__["_Settings__unexpected_args"]:
            self.__dict__["_Settings__unexpected_args"].update(
                settings.__dict__["_Settings__unexpected_args"]
            )

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

    def _apply_base(self, pid: int, _logger: Optional[_EarlyLogger] = None) -> None:
        if _logger is not None:
            _logger.info(f"Configure stats pid to {pid}")
        self.update({"_stats_pid": pid}, source=Source.SETUP)

    def _apply_config_files(self, _logger: Optional[_EarlyLogger] = None) -> None:
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

    def _apply_env_vars(
        self,
        environ: Mapping[str, Any],
        _logger: Optional[_EarlyLogger] = None,
    ) -> None:
        env_prefix: str = "WANDB_"
        special_env_var_names = {
            "WANDB_TRACELOG": "_tracelog",
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
                key = setting[len(env_prefix) :].lower()

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

    def _infer_settings_from_environment(
        self, _logger: Optional[_EarlyLogger] = None
    ) -> None:
        """Modify settings based on environment (for runs and cli)."""

        settings: Dict[str, Union[bool, str, Sequence, None]] = dict()
        # disable symlinks if on windows (requires admin or developer setup)
        settings["symlink"] = True
        if self._windows:
            settings["symlink"] = False

        # TODO(jhr): this needs to be moved last in setting up settings ?
        #  (dd): loading order does not matter as long as source is set correctly

        # For code saving, only allow env var override if value from server is true, or
        # if no preference was specified.
        if (self.save_code is True or self.save_code is None) and (
            os.getenv(wandb.env.SAVE_CODE) is not None
            or os.getenv(wandb.env.DISABLE_CODE) is not None
        ):
            settings["save_code"] = wandb.env.should_save_code()

        settings["disable_git"] = wandb.env.disable_git()

        # Attempt to get notebook information if not already set by the user
        if self._jupyter and (self.notebook_name is None or self.notebook_name == ""):
            meta = wandb.jupyter.notebook_metadata(self.silent)
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
                f"couldn't find {self.notebook_name}.",
            )

        # host and username are populated by apply_env_vars if corresponding env
        # vars exist -- but if they don't, we'll fill them in here
        if self.host is None:
            settings["host"] = socket.gethostname()  # type: ignore

        if self.username is None:
            try:  # type: ignore
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
        if not self._jupyter:
            settings["_args"] = sys.argv[1:]
        settings["_os"] = platform.platform(aliased=True)
        settings["_python"] = platform.python_version()
        # hack to make sure we don't hang on windows
        if self._windows and self._except_exit is None:
            settings["_except_exit"] = True  # type: ignore

        if _logger is not None:
            _logger.info(
                f"Inferring settings from compute environment: {_redact_dict(settings)}"
            )

        self.update(settings, source=Source.ENV)

    def _infer_run_settings_from_environment(
        self,
        _logger: Optional[_EarlyLogger] = None,
    ) -> None:
        """Modify settings based on environment (for runs only)."""
        # If there's not already a program file, infer it now.
        settings: Dict[str, Union[bool, str, None]] = dict()
        program = self.program or _get_program()
        if program is not None:
            program_relpath = self.program_relpath or _get_program_relpath_from_gitrepo(
                program, _logger=_logger
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

    def _apply_setup(
        self, setup_settings: Dict[str, Any], _logger: Optional[_EarlyLogger] = None
    ) -> None:
        if _logger:
            _logger.info(f"Applying setup settings: {_redact_dict(setup_settings)}")
        self.update(setup_settings, source=Source.SETUP)

    def _apply_user(
        self, user_settings: Dict[str, Any], _logger: Optional[_EarlyLogger] = None
    ) -> None:
        if _logger:
            _logger.info(f"Applying user settings: {_redact_dict(user_settings)}")
        self.update(user_settings, source=Source.USER)

    def _apply_init(self, init_settings: Dict[str, Union[str, int, None]]) -> None:
        # prevent setting project, entity if in sweep
        # TODO(jhr): these should be locked elements in the future
        if self.sweep_id:
            for key in ("project", "entity", "id"):
                val = init_settings.pop(key, None)
                if val:
                    wandb.termwarn(
                        f"Ignored wandb.init() arg {key} when running a sweep."
                    )
        if self.launch:
            for key in ("project", "entity", "id"):
                val = init_settings.pop(key, None)
                if val:
                    wandb.termwarn(
                        "Project, entity and id are ignored when running from wandb launch context. "
                        f"Ignored wandb.init() arg {key} when running running from launch.",
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
            param_map.get(k, k): v for k, v in init_settings.items() if v is not None
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
                    self.update({"run_id": resume_run_id}, source=Source.INIT)  # type: ignore
                elif self.run_id != resume_run_id:
                    wandb.termwarn(
                        "Tried to auto resume run with "
                        f"id {resume_run_id} but id {self.run_id} is set.",
                    )
        self.update({"run_id": self.run_id or generate_id()}, source=Source.INIT)
        # persist our run id in case of failure
        # check None for mypy
        if self.resume == "auto" and self.resume_fname is not None:
            wandb.util.mkdir_exists_ok(self.wandb_dir)
            with open(self.resume_fname, "w") as f:
                f.write(json.dumps({"run_id": self.run_id}))

    def _apply_login(
        self, login_settings: Dict[str, Any], _logger: Optional[_EarlyLogger] = None
    ) -> None:
        param_map = dict(key="api_key", host="base_url", timeout="login_timeout")
        login_settings = {
            param_map.get(k, k): v for k, v in login_settings.items() if v is not None
        }
        if login_settings:
            if _logger:
                _logger.info(f"Applying login settings: {_redact_dict(login_settings)}")
            self.update(login_settings, source=Source.LOGIN)

    def _apply_run_start(self, run_start_settings: Dict[str, Any]) -> None:
        # This dictionary maps from the "run message dict" to relevant fields in settings
        # Note: that config is missing
        param_map = {
            "run_id": "run_id",
            "entity": "entity",
            "project": "project",
            "run_group": "run_group",
            "job_type": "run_job_type",
            "display_name": "run_name",
            "notes": "run_notes",
            "tags": "run_tags",
            "sweep_id": "sweep_id",
            "host": "host",
            "resumed": "resumed",
            "git.remote_url": "git_remote_url",
            "git.commit": "git_commit",
        }
        run_settings = {
            name: reduce(lambda d, k: d.get(k, {}), attr.split("."), run_start_settings)
            for attr, name in param_map.items()
        }
        run_settings = {key: value for key, value in run_settings.items() if value}
        if run_settings:
            self.update(run_settings, source=Source.RUN)
