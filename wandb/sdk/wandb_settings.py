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
    Dict,
    FrozenSet,
    Iterable,
    Mapping,
    no_type_check,
    Optional,
    Sequence,
    Set,
    Tuple,
    TYPE_CHECKING,
    Union,
)

import wandb
from wandb import util
from wandb.errors import UsageError
from wandb.sdk.wandb_config import Config
from wandb.sdk.wandb_setup import _EarlyLogger

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
        wandb.termwarn(f"Path {path} wasn't writable, using system temp directory.")
        path = os.path.join(tempfile.gettempdir(), __stage_dir__ or ("wandb" + os.sep))

    return os.path.expanduser(path)


# fixme: should either return bool or error out. fix once confident.
def _str_as_bool(val: Union[str, bool, None]) -> Optional[bool]:
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

    # fixme: remove this and raise error instead once we are confident.
    wandb.termwarn(
        f"Could not parse value {val} as a bool. Defaulting to None."
        "This will raise an error in the future."
    )
    return None
    # raise UsageError(f"Could not parse value {val} as a bool.")


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
class SettingsConsole(enum.IntEnum):
    OFF = 0
    WRAP = 1
    REDIRECT = 2


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

    # fixme: this is a temporary measure to bypass validation of the settings
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
        is_policy: bool = False,
        frozen: bool = False,
        source: int = Source.BASE,
        **kwargs: Any,
    ):
        self.name = name
        self._preprocessor = preprocessor
        self._validator = validator
        self._hook = hook
        self._is_policy = is_policy
        self._source = source

        # fixme: this is a temporary measure to collect stats on failed validation
        self.__failed_validation: bool = False

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
                value = p(value)
        return value

    def _validate(self, value: Any) -> Any:
        self.__failed_validation = False  # fixme: this is a temporary measure
        if value is not None and self._validator is not None:
            _validator = (
                [self._validator] if callable(self._validator) else self._validator
            )
            for v in _validator:
                if not v(value):
                    # fixme: this is a temporary measure to bypass validation of certain settings.
                    #  remove this once we are confident
                    if self.name in self.__strict_validate_settings:
                        raise ValueError(
                            f"Invalid value for property {self.name}: {value}"
                        )
                    else:
                        wandb.termwarn(
                            f"Invalid value for property {self.name}: {value}. "
                            "This will raise an error in the future."
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
    _config_dict: Config
    _cuda: str
    _debug_log: str
    _disable_meta: bool
    _disable_stats: bool
    _disable_viewer: bool  # Prevent early viewer query
    _except_exit: bool
    _executable: str
    _internal_check_process: Union[int, float]
    _internal_queue_timeout: Union[int, float]
    _jupyter_name: str
    _jupyter_path: str
    _jupyter_root: str
    _os: str
    _python: str
    _require_service: str
    _runqueue_item_id: str
    _save_requirements: bool
    _service_transport: str
    _start_datetime: datetime
    _start_time: float
    _tmp_code_dir: str
    _unsaved_keys: Sequence[str]
    allow_val_change: bool
    anonymous: str
    api_key: str
    base_url: str  # The base url for the wandb api
    code_dir: str
    config_paths: Sequence[str]
    console: str
    disable_code: bool
    disable_git: bool
    disabled: bool  # Alias for mode=dryrun, not supported yet
    docker: str
    email: str
    entity: str
    files_dir: str
    force: bool
    git_remote: str
    heartbeat_seconds: int
    host: str
    ignore_globs: Tuple[str]
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
    quiet: bool
    reinit: bool
    relogin: bool
    resume: Union[str, int, bool]
    resume_fname: str
    root_dir: str
    run_group: str
    run_id: str
    run_job_type: str
    run_name: str
    run_notes: str
    run_tags: Tuple[str]
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
    symlink: bool
    sync_dir: str
    sync_file: str
    sync_symlink_latest: str
    system_sample: int
    system_sample_seconds: int
    tmp_dir: str
    username: str

    def _default_props(self) -> Dict[str, Dict[str, Any]]:
        """
        Helper method that is used in `__init__` together with the class attributes
        to initialize instance attributes (individual settings) as Property objects.
        Note that key names must be the same as the class attribute names.
        """
        return dict(
            _internal_check_process={"value": 8},
            _internal_queue_timeout={"value": 2},
            _save_requirements={"value": True},
            _tmp_code_dir={
                "value": "code",
                "hook": lambda x: self._path_convert(self.tmp_dir, x),
            },
            anonymous={"validator": self._validate_anonymous},
            base_url={
                "value": "https://api.wandb.ai",
                "preprocessor": lambda x: str(x).rstrip("/"),
                "validator": self._validate_base_url,
            },
            console={"value": "auto", "validator": self._validate_console},
            disable_code={"preprocessor": _str_as_bool, "is_policy": True},
            disable_git={"preprocessor": _str_as_bool, "is_policy": True},
            disabled={"value": False, "preprocessor": _str_as_bool},
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
            quiet={"preprocessor": _str_as_bool},
            reinit={"preprocessor": _str_as_bool},
            relogin={"preprocessor": _str_as_bool},
            resume_fname={
                "value": "wandb-resume.json",
                "hook": lambda x: self._path_convert(self.wandb_dir, x),
            },
            run_tags={
                "preprocessor": lambda x: tuple(x) if not isinstance(x, tuple) else x,
            },
            sagemaker_disable={"preprocessor": _str_as_bool},
            save_code={"preprocessor": _str_as_bool, "is_policy": True},
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
            symlink={"preprocessor": _str_as_bool},
            sync_dir={
                "value": "<sync_dir>",
                "validator": lambda x: isinstance(x, str),
                "hook": [
                    lambda x: self._path_convert(
                        self.wandb_dir, f"{self.run_mode}-{self.timespec}-{self.run_id}"
                    )
                ],
            },
            sync_file={
                "value": "run-<run_id>.wandb",
                "hook": lambda x: self._path_convert(
                    self.sync_dir, f"run-{self.run_id}.wandb"
                ),
            },
            sync_symlink_latest={
                "value": "latest-run",
                "hook": lambda x: self._path_convert(self.wandb_dir, x),
            },
            system_sample={"value": 15},
            system_sample_seconds={"value": 2},
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
            raise UsageError(
                f"Settings field `start_method`: '{value}' not in {available_methods}"
            )
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
                raise UsageError(
                    f"{value} is not a valid server address, did you mean https://api.wandb.ai?"
                )
            elif re.match(r".*wandb\.ai[^\.]*$", value) and "http://" in value:
                raise UsageError("http is not secure, please use https://api.wandb.ai")
        return True

    # other helper methods
    @staticmethod
    def _path_convert(*args: str) -> str:
        """
        Join path and apply os.path.expanduser to it.
        """
        return os.path.expanduser(os.path.join(*args))

    def _start_run(self) -> None:
        time_stamp: float = time.time()
        datetime_now: datetime = datetime.fromtimestamp(time_stamp)
        object.__setattr__(self, "_Settings_start_datetime", datetime_now)
        object.__setattr__(self, "_Settings_start_time", time_stamp)

    def __init__(self, **kwargs: Any) -> None:
        self.__frozen: bool = False
        self.__initialized: bool = False

        # fixme: this is collect telemetry on validation errors and unexpected args
        # values are stored as strings to avoid potential json serialization errors down the line
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
        # These are defaults, using Source.BASE for non-policy attributes and Source.ARGS for policies.
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
                        source=Source.ARGS
                        if default_props[prop].get("is_policy", False)
                        else Source.BASE,
                    ),
                )
            else:
                object.__setattr__(
                    self,
                    prop,
                    Property(name=prop, validator=validators, source=Source.BASE,),
                )

            # fixme: this is to collect stats on validation errors
            if self.__dict__[prop].__dict__["_Property__failed_validation"]:
                self.__validation_warnings[prop] = str(self.__dict__[prop]._value)

        # update overridden defaults from kwargs
        unexpected_arguments = [k for k in kwargs.keys() if k not in self.__dict__]
        # allow only explicitly defined arguments
        if unexpected_arguments:

            # fixme: remove this and raise error instead once we are confident
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
            source = Source.ARGS if self.__dict__[k].is_policy else Source.BASE
            self.update({k: v}, source=source)

        # setup private attributes
        object.__setattr__(self, "_Settings_start_datetime", None)
        object.__setattr__(self, "_Settings_start_time", None)

        if os.environ.get(wandb.env.DIR) is None:
            # todo: double-check source, shouldn't it be Source.ENV?
            self.update({"root_dir": os.path.abspath(os.getcwd())}, source=Source.BASE)

        # done with init, use self.update() to update attributes from now on
        self.__initialized = True

        # fixme? freeze settings to prevent accidental changes
        # self.freeze()

    def __str__(self) -> str:
        # get attributes that are instances of the Property class:
        attributes = {
            k: v.value for k, v in self.__dict__.items() if isinstance(v, Property)
        }
        # add @property-based settings:
        properties = {
            property_name: object.__getattribute__(self, property_name)
            for property_name, obj in self.__class__.__dict__.items()
            if isinstance(obj, property)
        }
        representation = {**attributes, **properties}
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
        # add @property-based settings:
        properties = {
            property_name: object.__getattribute__(self, property_name)
            for property_name, obj in self.__class__.__dict__.items()
            if isinstance(obj, property)
        }
        representation = {**private, **attributes, **properties}
        return f"<Settings {representation}>"

    def __copy__(self) -> "Settings":
        """
        Ensure that a copy of the settings object is a truly deep copy

        Note that the copied object will not be frozen  fixme? why is this needed?
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
        return iter(self.make_static(include_properties=True))

    def copy(self) -> "Settings":
        return self.__copy__()

    # implement the Mapping interface
    def keys(self) -> Iterable[str]:
        return self.make_static(include_properties=True).keys()

    @no_type_check  # this is a hack to make mypy happy
    def __getitem__(self, name: str) -> Any:
        """Expose attribute.value if attribute is a Property."""
        item = object.__getattribute__(self, name)
        if isinstance(item, Property):
            return item.value
        return item

    def update(
        self,
        settings: Optional[Dict[str, Any]] = None,
        source: int = Source.OVERRIDE,
        **kwargs: Any,
    ) -> None:
        """Update individual settings using the Property.update() method."""
        if "_Settings__frozen" in self.__dict__ and self.__frozen:
            raise TypeError("Settings object is frozen")
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

            # fixme: this is to collect stats on validation errors
            if self.__dict__[key].__dict__["_Property__failed_validation"]:
                self.__validation_warnings[key] = str(self.__dict__[key]._value)
            else:
                self.__validation_warnings.pop(key, None)

    def freeze(self) -> None:
        object.__setattr__(self, "_Settings__frozen", True)

    def unfreeze(self) -> None:
        object.__setattr__(self, "_Settings__frozen", False)

    def is_frozen(self) -> bool:
        return self.__frozen

    def make_static(self, include_properties: bool = True) -> Dict[str, Any]:
        """Generate a static, serializable version of the settings."""
        # get attributes that are instances of the Property class:
        attributes = {
            k: v.value for k, v in self.__dict__.items() if isinstance(v, Property)
        }
        # add @property-based settings:
        properties = {
            property_name: object.__getattribute__(self, property_name)
            for property_name, obj in self.__class__.__dict__.items()
            if isinstance(obj, property)
        }
        if include_properties:
            return {**attributes, **properties}
        return attributes

    # apply settings from different sources
    # TODO(dd): think about doing some|all of that at init
    def _apply_settings(
        self, settings: "Settings", _logger: Optional[_EarlyLogger] = None,
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

        # fixme: this is to pass on info on unexpected args in settings
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

    def _apply_config_files(self, _logger: Optional[_EarlyLogger] = None) -> None:
        # TODO(jhr): permit setting of config in system and workspace
        if self.settings_system is not None:
            if _logger is not None:
                _logger.info(f"Loading settings from {self.settings_system}")
            self.update(
                self._load_config_file(self.settings_system), source=Source.SYSTEM,
            )
        if self.settings_workspace is not None:
            if _logger is not None:
                _logger.info(f"Loading settings from {self.settings_workspace}")
            self.update(
                self._load_config_file(self.settings_workspace),
                source=Source.WORKSPACE,
            )

    def _apply_env_vars(
        self, environ: Mapping[str, Any], _logger: Optional[_EarlyLogger] = None,
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

    def infer_settings_from_environment(
        self, _logger: Optional[_EarlyLogger] = None
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
        if (self.save_code is True or self.save_code is None) and (
            os.getenv(wandb.env.SAVE_CODE) is not None
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
                f"couldn't find {self.notebook_name}."
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

    def infer_run_settings_from_environment(
        self, _logger: Optional[_EarlyLogger] = None,
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
                        f"Ignored wandb.init() arg {key} when running running from launch."
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
                        f"id {resume_run_id} but id {self.run_id} is set."
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
        return (self.mode == "disabled") is True

    @property
    def _offline(self) -> bool:
        if self.disabled or (self.mode in ("dryrun", "offline")):
            return True
        return False

    @property
    def _quiet(self) -> Any:
        return self.quiet

    @property
    def _show_info(self) -> Any:
        if not self.show_info:
            # fixme (dd): why?
            return None
        return self.show_info

    @property
    def _show_warnings(self) -> Any:
        if not self.show_warnings:
            # fixme (dd): why?
            return None
        return self.show_warnings

    @property
    def _show_errors(self) -> Any:
        if not self.show_errors:
            # fixme (dd): why?
            return None
        return self.show_errors

    @property
    def _silent(self) -> Any:
        return self.silent

    @property
    def _strict(self) -> Any:
        if not self.strict:
            # fixme (dd): why?
            return None
        return self.strict

    @property
    def _windows(self) -> bool:
        return platform.system() == "Windows"

    @property
    def is_local(self) -> bool:
        if self.base_url is not None:
            return (self.base_url == "https://api.wandb.ai") is False
        return False  # type: ignore

    @property
    def run_mode(self) -> str:
        return "offline-run" if self._offline else "run"

    @property
    def timespec(self) -> Optional[str]:
        if self._start_time and self._start_datetime:
            return datetime.strftime(self._start_datetime, "%Y%m%d_%H%M%S")
        return None

    @property
    def wandb_dir(self) -> str:
        return _get_wandb_dir(self.root_dir or "")
