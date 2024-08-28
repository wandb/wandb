import collections.abc
import configparser
import enum
import getpass
import json
import logging
import multiprocessing
import os
import platform
import re
import shutil
import socket
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from distutils.util import strtobool
from functools import reduce
from typing import (
    Any,
    Callable,
    Dict,
    FrozenSet,
    ItemsView,
    Iterable,
    Mapping,
    Optional,
    Sequence,
    Set,
    Tuple,
    Union,
    no_type_check,
)
from urllib.parse import quote, unquote, urlencode, urlparse, urlsplit

from google.protobuf.wrappers_pb2 import BoolValue, DoubleValue, Int32Value, StringValue

import wandb
import wandb.env
from wandb import util
from wandb.apis.internal import Api
from wandb.errors import UsageError
from wandb.proto import wandb_settings_pb2
from wandb.sdk.internal.system.env_probe_helpers import is_aws_lambda
from wandb.sdk.lib import credentials, filesystem
from wandb.sdk.lib._settings_toposort_generated import SETTINGS_TOPOLOGICALLY_SORTED
from wandb.sdk.lib.run_moment import RunMoment
from wandb.sdk.wandb_setup import _EarlyLogger

from .lib import apikey
from .lib.gitlib import GitRepo
from .lib.ipython import _get_python_type
from .lib.runid import generate_id

if sys.version_info >= (3, 8):
    from typing import get_args, get_origin, get_type_hints
else:
    from typing_extensions import get_args, get_origin, get_type_hints


class SettingsPreprocessingError(UsageError):
    """Raised when the value supplied to a wandb.Settings() setting does not pass preprocessing."""


class SettingsValidationError(UsageError):
    """Raised when the value supplied to a wandb.Settings() setting does not pass validation."""


class SettingsUnexpectedArgsError(UsageError):
    """Raised when unexpected arguments are passed to wandb.Settings()."""


def _get_wandb_dir(root_dir: str) -> str:
    """Get the full path to the wandb directory.

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


def _str_as_bool(val: Union[str, bool]) -> bool:
    """Parse a string as a bool."""
    if isinstance(val, bool):
        return val
    try:
        ret_val = bool(strtobool(str(val)))
        return ret_val
    except (AttributeError, ValueError):
        pass

    raise UsageError(f"Could not parse value {val} as a bool.")


def _str_as_json(val: Union[str, Dict[str, Any]]) -> Any:
    """Parse a string as a json object."""
    if not isinstance(val, str):
        return val
    try:
        return json.loads(val)
    except (AttributeError, ValueError):
        pass

    raise UsageError(f"Could not parse value {val} as JSON.")


def _str_as_tuple(val: Union[str, Sequence[str]]) -> Tuple[str, ...]:
    """Parse a (potentially comma-separated) string as a tuple."""
    if isinstance(val, str):
        return tuple(val.split(","))
    return tuple(val)


def _datetime_as_str(val: Union[datetime, str]) -> str:
    """Parse a datetime object as a string."""
    if isinstance(val, datetime):
        return datetime.strftime(val, "%Y%m%d_%H%M%S")
    return val


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


def _get_program() -> Optional[str]:
    program = os.getenv(wandb.env.PROGRAM)
    if program is not None:
        return program
    try:
        import __main__

        if __main__.__spec__ is None:
            return __main__.__file__
        # likely run as `python -m ...`
        return f"-m {__main__.__spec__.name}"
    except (ImportError, AttributeError):
        return None


def _runmoment_preprocessor(val: Any) -> Optional[RunMoment]:
    if isinstance(val, RunMoment) or val is None:
        return val
    elif isinstance(val, str):
        return RunMoment.from_uri(val)
    raise UsageError(f"Could not parse value {val} as a RunMoment.")


def _get_program_relpath(
    program: str, root: Optional[str] = None, _logger: Optional[_EarlyLogger] = None
) -> Optional[str]:
    if not program:
        if _logger is not None:
            _logger.warning("Empty program passed to get_program_relpath")
        return None

    root = root or os.getcwd()
    if not root:
        return None

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


def is_instance_recursive(obj: Any, type_hint: Any) -> bool:  # noqa: C901
    if type_hint is Any:
        return True

    origin = get_origin(type_hint)
    args = get_args(type_hint)

    if origin is None:
        return isinstance(obj, type_hint)

    if origin is Union:
        return any(is_instance_recursive(obj, arg) for arg in args)

    if issubclass(origin, collections.abc.Mapping):
        if not isinstance(obj, collections.abc.Mapping):
            return False
        key_type, value_type = args

        for key, value in obj.items():
            if not is_instance_recursive(key, key_type) or not is_instance_recursive(
                value, value_type
            ):
                return False

        return True

    if issubclass(origin, collections.abc.Sequence):
        if not isinstance(obj, collections.abc.Sequence) or isinstance(
            obj, (str, bytes, bytearray)
        ):
            return False

        if len(args) == 1 and args[0] != ...:
            (item_type,) = args
            for item in obj:
                if not is_instance_recursive(item, item_type):
                    return False
        elif len(args) == 2 and args[-1] == ...:
            item_type = args[0]
            for item in obj:
                if not is_instance_recursive(item, item_type):
                    return False
        elif len(args) == len(obj):
            for item, item_type in zip(obj, args):
                if not is_instance_recursive(item, item_type):
                    return False
        else:
            return False

        return True

    if issubclass(origin, collections.abc.Set):
        if not isinstance(obj, collections.abc.Set):
            return False

        (item_type,) = args
        for item in obj:
            if not is_instance_recursive(item, item_type):
                return False

        return True

    return False


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


ConsoleValue = {
    "auto",
    "off",
    "wrap",
    "redirect",
    # internal console states
    "wrap_raw",
    "wrap_emu",
}


@dataclass()
class SettingsData:
    """Settings for the W&B SDK."""

    _args: Sequence[str]
    _aws_lambda: bool
    _cli_only_mode: bool  # Avoid running any code specific for runs
    _code_path_local: str
    _colab: bool
    # _config_dict: Config
    _cuda: str
    _disable_meta: bool  # Do not collect system metadata
    _disable_service: (
        bool  # Disable wandb-service, spin up internal process the old way
    )
    _disable_setproctitle: bool  # Do not use setproctitle on internal process
    _disable_stats: bool  # Do not collect system metrics
    _disable_update_check: bool  # Disable version check
    _disable_viewer: bool  # Prevent early viewer query
    _disable_machine_info: bool  # Disable automatic machine info collection
    _executable: str
    _extra_http_headers: Mapping[str, str]
    _file_stream_max_bytes: int  # max size for filestream requests in core
    # file stream retry client configuration
    _file_stream_retry_max: int  # max number of retries
    _file_stream_retry_wait_min_seconds: float  # min wait time between retries
    _file_stream_retry_wait_max_seconds: float  # max wait time between retries
    _file_stream_timeout_seconds: float  # timeout for individual HTTP requests
    # file transfer retry client configuration
    _file_transfer_retry_max: int
    _file_transfer_retry_wait_min_seconds: float
    _file_transfer_retry_wait_max_seconds: float
    _file_transfer_timeout_seconds: float
    _flow_control_custom: bool
    _flow_control_disabled: bool
    # graphql retry client configuration
    _graphql_retry_max: int
    _graphql_retry_wait_min_seconds: float
    _graphql_retry_wait_max_seconds: float
    _graphql_timeout_seconds: float
    _internal_check_process: float
    _internal_queue_timeout: float
    _ipython: bool
    _jupyter: bool
    _jupyter_name: str
    _jupyter_path: str
    _jupyter_root: str
    _kaggle: bool
    _live_policy_rate_limit: int
    _live_policy_wait_time: int
    _log_level: int
    _network_buffer: int
    _noop: bool
    _notebook: bool
    _offline: bool
    _sync: bool
    _os: str
    _platform: str
    _proxies: Mapping[
        str, str
    ]  # custom proxy servers for the requests to W&B [scheme -> url]
    _python: str
    _runqueue_item_id: str
    _require_core: bool
    _require_legacy_service: bool
    _save_requirements: bool
    _service_transport: str
    _service_wait: float
    _shared: bool
    _start_datetime: str
    _start_time: float
    _stats_pid: int  # (internal) base pid for system stats
    _stats_sample_rate_seconds: float
    _stats_samples_to_average: int
    _stats_join_assets: (
        bool  # join metrics from different assets before sending to backend
    )
    _stats_neuron_monitor_config_path: (
        str  # path to place config file for neuron-monitor (AWS Trainium)
    )
    _stats_open_metrics_endpoints: Mapping[str, str]  # open metrics endpoint names/urls
    # open metrics filters in one of the two formats:
    # - {"metric regex pattern, including endpoint name as prefix": {"label": "label value regex pattern"}}
    # - ("metric regex pattern 1", "metric regex pattern 2", ...)
    _stats_open_metrics_filters: Union[Sequence[str], Mapping[str, Mapping[str, str]]]
    _stats_disk_paths: Sequence[str]  # paths to monitor disk usage
    _stats_buffer_size: int  # number of consolidated samples to buffer before flushing, available in run obj
    _tmp_code_dir: str
    _tracelog: str
    _unsaved_keys: Sequence[str]
    _windows: bool
    allow_val_change: bool
    anonymous: str
    api_key: str
    azure_account_url_to_access_key: Dict[str, str]
    base_url: str  # The base url for the wandb api
    code_dir: str
    colab_url: str
    config_paths: Sequence[str]
    console: str
    console_multipart: bool  # whether to produce multipart console log files
    credentials_file: str  # file path to write access tokens
    deployment: str
    disable_code: bool
    disable_git: bool
    disable_hints: bool
    disable_job_creation: bool
    disabled: bool  # Alias for mode=dryrun, not supported yet
    docker: str
    email: str
    entity: str
    files_dir: str
    force: bool
    fork_from: Optional[RunMoment]
    resume_from: Optional[RunMoment]
    git_commit: str
    git_remote: str
    git_remote_url: str
    git_root: str
    heartbeat_seconds: int
    host: str
    http_proxy: str  # proxy server for the http requests to W&B
    https_proxy: str  # proxy server for the https requests to W&B
    identity_token_file: str  # file path to supply a jwt for authentication
    ignore_globs: Tuple[str]
    init_timeout: float
    is_local: bool
    job_name: str
    job_source: str
    label_disable: bool
    launch: bool
    launch_config_path: str
    log_dir: str
    log_internal: str
    log_symlink_internal: str
    log_symlink_user: str
    log_user: str
    login_timeout: float
    # magic: Union[str, bool, dict]  # never used in code, deprecated
    mode: str
    notebook_name: str
    program: str
    program_abspath: str
    program_relpath: str
    project: str
    project_url: str
    quiet: bool
    reinit: bool
    relogin: bool
    # todo: add a preprocessing step to convert this to string
    resume: Union[str, bool]
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
    summary_timeout: int
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
    table_raise_on_max_row_limit_exceeded: bool
    timespec: str
    tmp_dir: str
    username: str
    wandb_dir: str


class Property:
    """A class to represent attributes (individual settings) of the Settings object.

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
                except Exception:
                    raise SettingsPreprocessingError(
                        f"Unable to preprocess value for property {self.name}: {value}."
                    )
        return value

    def _validate(self, value: Any) -> Any:
        if value is not None and self._validator is not None:
            _validator = (
                [self._validator] if callable(self._validator) else self._validator
            )
            for v in _validator:
                if not v(value):
                    # failed validation will likely cause a downstream error
                    # when trying to convert to protobuf, so we raise a hard error
                    raise SettingsValidationError(
                        f"Invalid value for property {self.name}: {value}."
                    )
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
        return f"{self.value!r}" if isinstance(self.value, str) else f"{self.value}"

    def __repr__(self) -> str:
        return (
            f"<Property {self.name}: value={self.value} "
            f"_value={self._value} source={self._source} is_policy={self._is_policy}>"
        )
        # return f"<Property {self.name}: value={self.value}>"
        # return self.__dict__.__repr__()


class Settings(SettingsData):
    """A class to represent modifiable settings."""

    def _default_props(self) -> Dict[str, Dict[str, Any]]:
        """Initialize instance attributes (individual settings) as Property objects.

        Helper method that is used in `__init__` together with the class attributes.
        Note that key names must be the same as the class attribute names.
        """
        props: Dict[str, Dict[str, Any]] = dict(
            _aws_lambda={
                "hook": lambda _: is_aws_lambda(),
                "auto_hook": True,
            },
            _code_path_local={
                "hook": lambda _: _get_program_relpath(self.program),
                "auto_hook": True,
            },
            _colab={
                "hook": lambda _: "google.colab" in sys.modules,
                "auto_hook": True,
            },
            _disable_machine_info={
                "value": False,
                "preprocessor": _str_as_bool,
            },
            _disable_meta={
                "value": False,
                "preprocessor": _str_as_bool,
                "hook": lambda x: self._disable_machine_info or x,
            },
            _disable_service={
                "value": False,
                "preprocessor": self._process_disable_service,
                "is_policy": True,
            },
            _disable_setproctitle={"value": False, "preprocessor": _str_as_bool},
            _disable_stats={
                "value": False,
                "preprocessor": _str_as_bool,
                "hook": lambda x: self._disable_machine_info or x,
            },
            _disable_update_check={"preprocessor": _str_as_bool},
            _disable_viewer={"preprocessor": _str_as_bool},
            _extra_http_headers={"preprocessor": _str_as_json},
            _file_stream_max_bytes={"preprocessor": int},
            _file_stream_retry_max={"preprocessor": int},
            _file_stream_retry_wait_min_seconds={"preprocessor": float},
            _file_stream_retry_wait_max_seconds={"preprocessor": float},
            _file_stream_timeout_seconds={"preprocessor": float},
            _file_transfer_retry_max={"preprocessor": int},
            _file_transfer_retry_wait_min_seconds={"preprocessor": float},
            _file_transfer_retry_wait_max_seconds={"preprocessor": float},
            _file_transfer_timeout_seconds={"preprocessor": float},
            _flow_control_disabled={
                "hook": lambda _: self._network_buffer == 0,
                "auto_hook": True,
            },
            _flow_control_custom={
                "hook": lambda _: bool(self._network_buffer),
                "auto_hook": True,
            },
            _graphql_retry_max={"preprocessor": int},
            _graphql_retry_wait_min_seconds={"preprocessor": float},
            _graphql_retry_wait_max_seconds={"preprocessor": float},
            _graphql_timeout_seconds={"preprocessor": float},
            _internal_check_process={"value": 8, "preprocessor": float},
            _internal_queue_timeout={"value": 2, "preprocessor": float},
            _ipython={
                "hook": lambda _: _get_python_type() == "ipython",
                "auto_hook": True,
            },
            _jupyter={
                "hook": lambda _: _get_python_type() == "jupyter",
                "auto_hook": True,
            },
            _kaggle={"hook": lambda _: util._is_likely_kaggle(), "auto_hook": True},
            _log_level={"value": logging.DEBUG},
            _network_buffer={"preprocessor": int},
            _noop={"hook": lambda _: self.mode == "disabled", "auto_hook": True},
            _notebook={
                "hook": lambda _: self._ipython
                or self._jupyter
                or self._colab
                or self._kaggle,
                "auto_hook": True,
            },
            _offline={
                "hook": (
                    lambda _: True
                    if self.disabled or (self.mode in ("dryrun", "offline"))
                    else False
                ),
                "auto_hook": True,
            },
            _platform={"value": util.get_platform_name()},
            _proxies={
                # TODO: deprecate and ask the user to use http_proxy and https_proxy instead
                "preprocessor": _str_as_json,
            },
            _require_core={"value": False, "preprocessor": _str_as_bool},
            _require_legacy_service={"value": False, "preprocessor": _str_as_bool},
            _save_requirements={"value": True, "preprocessor": _str_as_bool},
            _service_wait={
                "value": 30,
                "preprocessor": float,
                "validator": self._validate__service_wait,
            },
            _shared={
                "hook": lambda _: self.mode == "shared",
                "auto_hook": True,
            },
            _start_datetime={"preprocessor": _datetime_as_str},
            _stats_sample_rate_seconds={
                "value": 2.0,
                "preprocessor": float,
                "validator": self._validate__stats_sample_rate_seconds,
            },
            _stats_samples_to_average={
                "value": 15,
                "preprocessor": int,
                "validator": self._validate__stats_samples_to_average,
            },
            _stats_join_assets={"value": True, "preprocessor": _str_as_bool},
            _stats_neuron_monitor_config_path={
                "hook": lambda x: self._path_convert(x),
            },
            _stats_open_metrics_endpoints={
                "preprocessor": _str_as_json,
            },
            _stats_open_metrics_filters={
                # capture all metrics on all endpoints by default
                "value": (".*",),
                "preprocessor": _str_as_json,
            },
            _stats_disk_paths={
                "value": ("/",),
                "preprocessor": _str_as_json,
            },
            _stats_buffer_size={
                "value": 0,
                "preprocessor": int,
            },
            _sync={"value": False},
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
            colab_url={
                "hook": lambda _: self._get_colab_url(),
                "auto_hook": True,
            },
            config_paths={"preprocessor": _str_as_tuple},
            console={
                "value": "auto",
                "validator": self._validate_console,
                "hook": lambda x: self._convert_console(x),
                "auto_hook": True,
            },
            console_multipart={"value": False, "preprocessor": _str_as_bool},
            credentials_file={
                "value": str(credentials.DEFAULT_WANDB_CREDENTIALS_FILE),
                "preprocessor": str,
            },
            deployment={
                "hook": lambda _: "local" if self.is_local else "cloud",
                "auto_hook": True,
            },
            disable_code={
                "value": False,
                "preprocessor": _str_as_bool,
                "hook": lambda x: self._disable_machine_info or x,
            },
            disable_hints={"preprocessor": _str_as_bool},
            disable_git={
                "value": False,
                "preprocessor": _str_as_bool,
                "hook": lambda x: self._disable_machine_info or x,
            },
            disable_job_creation={
                "value": False,
                "preprocessor": _str_as_bool,
                "hook": lambda x: self._disable_machine_info or x,
            },
            disabled={"value": False, "preprocessor": _str_as_bool},
            files_dir={
                "value": "files",
                "hook": lambda x: self._path_convert(
                    self.wandb_dir, f"{self.run_mode}-{self.timespec}-{self.run_id}", x
                ),
            },
            force={"preprocessor": _str_as_bool},
            fork_from={
                "value": None,
                "preprocessor": _runmoment_preprocessor,
            },
            resume_from={
                "value": None,
                "preprocessor": _runmoment_preprocessor,
            },
            git_remote={"value": "origin"},
            heartbeat_seconds={"value": 30},
            http_proxy={
                "hook": lambda x: self._proxies and self._proxies.get("http") or x,
                "auto_hook": True,
            },
            https_proxy={
                "hook": lambda x: self._proxies and self._proxies.get("https") or x,
                "auto_hook": True,
            },
            identity_token_file={"value": None, "preprocessor": str},
            ignore_globs={
                "value": tuple(),
                "preprocessor": lambda x: tuple(x) if not isinstance(x, tuple) else x,
            },
            init_timeout={"value": 90, "preprocessor": lambda x: float(x)},
            is_local={
                "hook": (
                    lambda _: self.base_url != "https://api.wandb.ai"
                    if self.base_url is not None
                    else False
                ),
                "auto_hook": True,
            },
            job_name={"preprocessor": str},
            job_source={"validator": self._validate_job_source},
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
            program={
                "hook": lambda x: self._get_program(x),
            },
            project={
                "validator": self._validate_project,
            },
            project_url={"hook": lambda _: self._project_url(), "auto_hook": True},
            quiet={"preprocessor": _str_as_bool},
            reinit={"preprocessor": _str_as_bool},
            relogin={"preprocessor": _str_as_bool},
            # todo: hack to make to_proto() always happy
            resume={"preprocessor": lambda x: None if x is False else x},
            resume_fname={
                "value": "wandb-resume.json",
                "hook": lambda x: self._path_convert(self.wandb_dir, x),
            },
            resumed={"value": "False", "preprocessor": _str_as_bool},
            root_dir={
                "preprocessor": lambda x: str(x),
                "value": os.path.abspath(os.getcwd()),
            },
            run_id={
                "validator": self._validate_run_id,
            },
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
            summary_timeout={"value": 60, "preprocessor": lambda x: int(x)},
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
                "hook": lambda _: self._start_datetime,
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
        return props

    # helper methods for validating values
    @staticmethod
    def _validator_factory(hint: Any) -> Callable[[Any], bool]:  # noqa: C901
        """Return a factory for setting type validators."""

        def helper(value: Any) -> bool:
            try:
                is_valid = is_instance_recursive(value, hint)
            except Exception:
                # instance check failed, but let's not crash and only print a warning
                is_valid = False

            return is_valid

        return helper

    @staticmethod
    def _validate_mode(value: str) -> bool:
        choices: Set[str] = {"dryrun", "run", "offline", "online", "disabled", "shared"}
        if value not in choices:
            raise UsageError(f"Settings field `mode`: {value!r} not in {choices}")
        return True

    @staticmethod
    def _validate_project(value: Optional[str]) -> bool:
        invalid_chars_list = list("/\\#?%:")
        if value is not None:
            if len(value) > 128:
                raise UsageError(
                    f"Invalid project name {value!r}: exceeded 128 characters"
                )
            invalid_chars = {char for char in invalid_chars_list if char in value}
            if invalid_chars:
                raise UsageError(
                    f"Invalid project name {value!r}: "
                    f"cannot contain characters {','.join(invalid_chars_list)!r}, "
                    f"found {','.join(invalid_chars)!r}"
                )
        return True

    @staticmethod
    def _validate_start_method(value: str) -> bool:
        available_methods = ["thread"]
        if hasattr(multiprocessing, "get_all_start_methods"):
            available_methods += multiprocessing.get_all_start_methods()
        if value not in available_methods:
            raise UsageError(
                f"Settings field `start_method`: {value!r} not in {available_methods}"
            )
        return True

    @staticmethod
    def _validate_console(value: str) -> bool:
        choices = ConsoleValue
        if value not in choices:
            # do not advertise internal console states
            choices -= {"wrap_emu", "wrap_raw"}
            raise UsageError(f"Settings field `console`: {value!r} not in {choices}")
        return True

    @staticmethod
    def _validate_anonymous(value: str) -> bool:
        choices: Set[str] = {"allow", "must", "never", "false", "true"}
        if value not in choices:
            raise UsageError(f"Settings field `anonymous`: {value!r} not in {choices}")
        return True

    @staticmethod
    def _validate_run_id(value: str) -> bool:
        # if len(value) > len(value.strip()):
        #     raise UsageError("Run ID cannot start or end with whitespace")
        return bool(value.strip())

    @staticmethod
    def _validate_api_key(value: str) -> bool:
        if len(value) > len(value.strip()):
            raise UsageError("API key cannot start or end with whitespace")

        # todo: move this check to the post-init validation step
        # if value.startswith("local") and not self.is_local:
        #     raise UsageError(
        #         "Attempting to use a local API key to connect to https://api.wandb.ai"
        #     )
        # todo: move here the logic from sdk/lib/apikey.py

        return True

    @staticmethod
    def _validate_base_url(value: Optional[str]) -> bool:
        """Validate the base url of the wandb server.

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

    @staticmethod
    def _process_disable_service(value: Union[str, bool]) -> bool:
        value = _str_as_bool(value)
        if value:
            wandb.termwarn(
                "Disabling the wandb service is deprecated as of version 0.18.0 and will be removed in version 0.19.0.",
                repeat=False,
            )
        return value

    @staticmethod
    def _validate__service_wait(value: float) -> bool:
        if value <= 0:
            raise UsageError("_service_wait must be a positive number")
        return True

    @staticmethod
    def _validate__stats_sample_rate_seconds(value: float) -> bool:
        if value < 0.1:
            raise UsageError("_stats_sample_rate_seconds must be >= 0.1")
        return True

    @staticmethod
    def _validate__stats_samples_to_average(value: int) -> bool:
        if value < 1 or value > 30:
            raise UsageError("_stats_samples_to_average must be between 1 and 30")
        return True

    @staticmethod
    def _validate_job_source(value: str) -> bool:
        valid_sources = ["repo", "artifact", "image"]
        if value not in valid_sources:
            raise UsageError(
                f"Settings field `job_source`: {value!r} not in {valid_sources}"
            )
        return True

    # other helper methods
    @staticmethod
    def _path_convert(*args: str) -> str:
        """Join path and apply os.path.expanduser to it."""
        return os.path.expanduser(os.path.join(*args))

    def _convert_console(self, console: str) -> str:
        if console == "auto":
            if (
                self._jupyter
                or (self.start_method == "thread")
                or not self._disable_service
                or self._windows
            ):
                console = "wrap"
            else:
                console = "redirect"
        return console

    def _get_colab_url(self) -> Optional[str]:
        if not self._colab:
            return None
        if self._jupyter_path and self._jupyter_path.startswith("fileId="):
            unescaped = unquote(self._jupyter_path)
            return "https://colab.research.google.com/notebook#" + unescaped
        return None

    def _get_program(self, program: Optional[str]) -> Optional[str]:
        if program is not None and program != "<python with no main file>":
            return program

        if not self._jupyter:
            return program

        if self.notebook_name:
            return self.notebook_name

        if not self._jupyter_path:
            return program

        if self._jupyter_path.startswith("fileId="):
            return self._jupyter_name
        else:
            return self._jupyter_path

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
        """Return the run url."""
        project_url = self._project_url_base()
        if not all([project_url, self.run_id]):
            return ""

        query = self._get_url_query_string()
        return f"{project_url}/runs/{quote(self.run_id)}{query}"

    def _set_run_start_time(self, source: int = Source.BASE) -> None:
        """Set the time stamps for the settings.

        Called once the run is initialized.
        """
        time_stamp: float = time.time()
        datetime_now: datetime = datetime.fromtimestamp(time_stamp)
        datetime_now_str = _datetime_as_str(datetime_now)
        object.__setattr__(self, "_Settings_start_datetime", datetime_now_str)
        object.__setattr__(self, "_Settings_start_time", time_stamp)
        self.update(
            _start_datetime=datetime_now_str,
            _start_time=time_stamp,
            source=source,
        )

    def _sweep_url(self) -> str:
        """Return the sweep url."""
        project_url = self._project_url_base()
        if not all([project_url, self.sweep_id]):
            return ""

        query = self._get_url_query_string()
        return f"{project_url}/sweeps/{quote(self.sweep_id)}{query}"

    def __init__(self, **kwargs: Any) -> None:
        self.__frozen: bool = False
        self.__initialized: bool = False

        self.__modification_order = SETTINGS_TOPOLOGICALLY_SORTED

        # Set default settings values
        # We start off with the class attributes and `default_props` dicts
        # and then create Property objects.
        # Once initialized, attributes are to only be updated using the `update` method
        default_props = self._default_props()

        # Init instance attributes as Property objects.
        # Type hints of class attributes are used to generate a type validator function
        # for runtime checks for each attribute.
        # These are defaults, using Source.BASE for non-policy attributes and Source.RUN for policies.
        for prop, type_hint in get_type_hints(SettingsData).items():
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

        # update overridden defaults from kwargs
        unexpected_arguments = [k for k in kwargs.keys() if k not in self.__dict__]
        # allow only explicitly defined arguments
        if unexpected_arguments:
            raise SettingsUnexpectedArgsError(
                f"Got unexpected arguments: {unexpected_arguments}. "
            )

        # automatically inspect setting validators and runtime hooks and topologically sort them
        # so that we can safely update them. throw error if there are cycles.
        for prop in self.__modification_order:
            if prop in kwargs:
                source = Source.RUN if self.__dict__[prop].is_policy else Source.BASE
                self.update({prop: kwargs[prop]}, source=source)
                kwargs.pop(prop)

        for k, v in kwargs.items():
            # todo: double-check this logic:
            source = Source.RUN if self.__dict__[k].is_policy else Source.BASE
            self.update({k: v}, source=source)

        # setup private attributes
        object.__setattr__(self, "_Settings_start_datetime", None)
        object.__setattr__(self, "_Settings_start_time", None)

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
        """Ensure that a copy of the settings object is a truly deep copy.

        Note that the copied object will not be frozen  todo? why is this needed?
        """
        # get attributes that are instances of the Property class:
        attributes = {k: v for k, v in self.__dict__.items() if isinstance(v, Property)}
        new = Settings()
        # update properties that have deps or are dependent on in the topologically-sorted order
        for prop in self.__modification_order:
            new.update({prop: attributes[prop]._value}, source=attributes[prop].source)
            attributes.pop(prop)

        # update the remaining attributes
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
        """Expose `attribute.value` if `attribute` is a Property."""
        item = object.__getattribute__(self, name)
        if isinstance(item, Property):
            return item.value
        return item

    def __setattr__(self, key: str, value: Any) -> None:
        if "_Settings__initialized" in self.__dict__ and self.__initialized:
            raise TypeError(f"Please use update() to update attribute `{key}` value")
        object.__setattr__(self, key, value)

    def __iter__(self) -> Iterable:
        return iter(self.to_dict())

    def copy(self) -> "Settings":
        return self.__copy__()

    # implement the Mapping interface
    def keys(self) -> Iterable[str]:
        return self.to_dict().keys()

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
        """Update individual settings."""
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

        # store settings to be updated in a dict to preserve stats on preprocessing and validation errors
        settings.copy()

        # update properties that have deps or are dependent on in the topologically-sorted order
        for key in self.__modification_order:
            if key in settings:
                self.__dict__[key].update(settings.pop(key), source=source)

        # update the remaining properties
        for key, value in settings.items():
            self.__dict__[key].update(value, source)

    def items(self) -> ItemsView[str, Any]:
        return self.to_dict().items()

    def get(self, key: str, default: Optional[Any] = None) -> Any:
        return self.to_dict().get(key, default)

    def freeze(self) -> None:
        object.__setattr__(self, "_Settings__frozen", True)

    def unfreeze(self) -> None:
        object.__setattr__(self, "_Settings__frozen", False)

    def is_frozen(self) -> bool:
        return self.__frozen

    def to_dict(self) -> Dict[str, Any]:
        """Return a dict representation of the settings."""
        # get attributes that are instances of the Property class:
        attributes = {
            k: v.value for k, v in self.__dict__.items() if isinstance(v, Property)
        }
        return attributes

    def to_proto(self) -> wandb_settings_pb2.Settings:
        """Generate a protobuf representation of the settings."""
        from dataclasses import fields

        settings = wandb_settings_pb2.Settings()
        for field in fields(SettingsData):
            k = field.name
            v = getattr(self, k)
            # special case for _stats_open_metrics_filters
            if k == "_stats_open_metrics_filters":
                if isinstance(v, (list, set, tuple)):
                    setting = getattr(settings, k)
                    setting.sequence.value.extend(v)
                elif isinstance(v, dict):
                    setting = getattr(settings, k)
                    for key, value in v.items():
                        for kk, vv in value.items():
                            setting.mapping.value[key].value[kk] = vv
                else:
                    raise TypeError(f"Unsupported type {type(v)} for setting {k}")
                continue

            if isinstance(v, bool):
                getattr(settings, k).CopyFrom(BoolValue(value=v))
            elif isinstance(v, int):
                getattr(settings, k).CopyFrom(Int32Value(value=v))
            elif isinstance(v, float):
                getattr(settings, k).CopyFrom(DoubleValue(value=v))
            elif isinstance(v, str):
                getattr(settings, k).CopyFrom(StringValue(value=v))
            elif isinstance(v, (list, set, tuple)):
                # we only support sequences of strings for now
                sequence = getattr(settings, k)
                sequence.value.extend(v)
            elif isinstance(v, dict):
                mapping = getattr(settings, k)
                for key, value in v.items():
                    # we only support dicts with string values for now
                    mapping.value[key] = value
            elif isinstance(v, RunMoment):
                getattr(settings, k).CopyFrom(
                    wandb_settings_pb2.RunMoment(
                        run=v.run,
                        value=v.value,
                        metric=v.metric,
                    )
                )
            elif v is None:
                # None is the default value for all settings, so we don't need to set it,
                # i.e. None means that the value was not set.
                pass
            else:
                raise TypeError(f"Unsupported type {type(v)} for setting {k}")
        # TODO: store property sources in the protobuf so that we can reconstruct the
        #  settings object from the protobuf
        return settings

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
        # update properties that have deps or are dependent on in the topologically-sorted order
        for prop in self.__modification_order:
            self.update({prop: attributes[prop]._value}, source=attributes[prop].source)
            attributes.pop(prop)
        # update the remaining properties
        for k, v in attributes.items():
            # note that only the same/higher priority settings are propagated
            self.update({k: v._value}, source=v.source)

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
            _logger.info(f"Current SDK version is {wandb.__version__}")
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
            "WANDB_DISABLE_SERVICE": "_disable_service",
            "WANDB_SERVICE_TRANSPORT": "_service_transport",
            "WANDB_DIR": "root_dir",
            "WANDB_NAME": "run_name",
            "WANDB_NOTES": "run_notes",
            "WANDB_TAGS": "run_tags",
            "WANDB_JOB_TYPE": "run_job_type",
            "WANDB_HTTP_TIMEOUT": "_graphql_timeout_seconds",
            "WANDB_FILE_PUSHER_TIMEOUT": "_file_transfer_timeout_seconds",
            "WANDB_USER_EMAIL": "email",
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
            meta = wandb.jupyter.notebook_metadata(self.silent)  # type: ignore
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

        _executable = (
            self._executable
            or os.environ.get(wandb.env._EXECUTABLE)
            or sys.executable
            or shutil.which("python3")
            or "python3"
        )
        settings["_executable"] = _executable

        settings["docker"] = wandb.env.get_docker(wandb.util.image_id_from_k8s())

        # TODO: we should use the cuda library to collect this
        if os.path.exists("/usr/local/cuda/version.txt"):
            with open("/usr/local/cuda/version.txt") as f:
                settings["_cuda"] = f.read().split(" ")[-1].strip()
        if not self._jupyter:
            settings["_args"] = sys.argv[1:]
        settings["_os"] = platform.platform(aliased=True)
        settings["_python"] = platform.python_version()

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
            repo = GitRepo()
            root = repo.root or os.getcwd()

            program_relpath = self.program_relpath or _get_program_relpath(
                program, repo.root, _logger=_logger
            )
            settings["program_relpath"] = program_relpath
            program_abspath = os.path.abspath(
                os.path.join(root, os.path.relpath(os.getcwd(), root), program)
            )
            if os.path.exists(program_abspath):
                settings["program_abspath"] = program_abspath
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
        # pop magic from init settings
        init_settings.pop("magic", None)

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
            if self.project is not None and init_settings.pop("project", None):
                wandb.termwarn(
                    "Project is ignored when running from wandb launch context. "
                    "Ignored wandb.init() arg project when running running from launch.",
                )
            for key in ("entity", "id"):
                # Init settings cannot override launch settings.
                if init_settings.pop(key, None):
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
            sweep_id="sweep_id",
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
                # todo: add deprecation warning, switch to literal strings for resume
                init_settings["resume"] = "auto"

        # update settings
        self.update(init_settings, source=Source.INIT)
        self._handle_fork_logic()
        self._handle_rewind_logic()
        self._handle_resume_logic()

    def _handle_fork_logic(self) -> None:
        if self.fork_from is None:
            return

        if self.run_id is not None and (self.fork_from.run == self.run_id):
            raise ValueError(
                "Provided `run_id` is the same as the run to `fork_from`. "
                "Please provide a different `run_id` or remove the `run_id` argument. "
                "If you want to rewind the current run, please use `resume_from` instead."
            )

    def _handle_rewind_logic(self) -> None:
        if self.resume_from is None:
            return

        if self.run_id is not None and (self.resume_from.run != self.run_id):
            wandb.termwarn(
                "Both `run_id` and `resume_from` have been specified with different ids. "
                "`run_id` will be ignored."
            )
        self.update({"run_id": self.resume_from.run}, source=Source.INIT)

    def _handle_resume_logic(self) -> None:
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
            filesystem.mkdir_exists_ok(self.wandb_dir)
            with open(self.resume_fname, "w") as f:
                f.write(json.dumps({"run_id": self.run_id}))

    def _apply_login(
        self,
        login_settings: Dict[str, Any],
        _logger: Optional[_EarlyLogger] = None,
    ) -> None:
        key_map = {
            "key": "api_key",
            "host": "base_url",
            "timeout": "login_timeout",
        }

        # Rename keys and keep only the non-None values.
        #
        # The input keys are parameters to wandb.login(), but we use different
        # names for some of them in Settings.
        login_settings = {
            key_map.get(key, key): value
            for key, value in login_settings.items()
            if value is not None
        }

        if _logger:
            _logger.info(f"Applying login settings: {_redact_dict(login_settings)}")

        self.update(
            login_settings,
            source=Source.LOGIN,
        )

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
