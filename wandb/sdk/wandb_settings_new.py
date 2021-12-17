from datetime import datetime
from distutils.util import strtobool
import enum
import multiprocessing
import os
import platform
import re
import tempfile
import time
from typing import (
    Any,
    Callable,
    cast,
    Dict,
    no_type_check,
    Optional,
    Set,
    Sequence,
    Tuple,
    Type,
    TYPE_CHECKING,
    Union,
)
from urllib.parse import urljoin

import wandb
from wandb import util
from wandb.errors import UsageError
from wandb.sdk.wandb_config import Config

from .lib.ipython import _get_python_type


def _build_inverse_map(prefix: str, d: Dict[str, Optional[str]]) -> Dict[str, str]:
    return {v or prefix + k.upper(): k for k, v in d.items()}


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

    return path


def _str_as_bool(val: Union[str, bool, None]) -> Optional[bool]:
    ret_val = None
    if isinstance(val, bool):
        return val
    try:
        ret_val = bool(strtobool(val))
    except (AttributeError, ValueError):
        pass
    return ret_val


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
        self._args = {
            "value": None,
            "validator": lambda x: isinstance(x, list),
        }
        self._cli_only_mode = {
            "value": None,
            "validator": lambda x: isinstance(x, bool),
            "help": "Avoid running any code specific for runs",
        }
        self._config_dict = {
            "value": None,
            "validator": lambda x: isinstance(x, Config),
        }
        self._cuda = {
            "value": None,
            "validator": lambda x: isinstance(x, bool),
        }
        self._debug_log = {
            "value": None,
            "validator": lambda x: isinstance(x, str),
        }
        self._disable_meta = {
            "value": None,
            "validator": lambda x: isinstance(x, bool),
        }
        self._disable_stats = {
            "value": None,
            "validator": lambda x: isinstance(x, bool),
        }
        self._disable_viewer = {
            "value": None,
            "validator": lambda x: isinstance(x, bool),
            "help": "Prevent early viewer query",
        }
        self._except_exit = {
            # fixme? elsewhere it is str
            "value": None,
            "validator": lambda x: isinstance(x, bool),
        }
        self._executable = {
            "value": None,
            "validator": lambda x: isinstance(x, str),
        }
        self._internal_check_process = {
            "value": 8,
            "validator": lambda x: isinstance(x, int) or isinstance(x, float),
        }
        self._internal_queue_timeout = {
            "value": 2,
            "validator": lambda x: isinstance(x, int) or isinstance(x, float),
        }
        self._jupyter_name = {
            "value": None,
            "validator": lambda x: isinstance(x, str),
        }
        self._jupyter_path = {
            "value": None,
            "validator": lambda x: isinstance(x, str),
        }
        self._jupyter_root = {
            "value": None,
            "validator": lambda x: isinstance(x, str),
        }
        self._kaggle = {
            "value": None,
            "validator": lambda x: isinstance(x, str),
        }
        self._os = {
            "value": None,
            "validator": lambda x: isinstance(x, str),
        }
        self._python = {
            "value": None,
            "validator": lambda x: isinstance(x, str),
        }
        self._require_service = {
            "value": None,
            "validator": lambda x: isinstance(x, str),
        }
        self._runqueue_item_id = {
            "value": None,
            "validator": lambda x: isinstance(x, str),
        }
        self._save_requirements = {
            "value": True,
            "validator": lambda x: isinstance(x, bool),
        }
        self._service_transport = {
            "value": None,
            "validator": lambda x: isinstance(x, str),
        }
        self._start_datetime = {
            "value": None,
            "validator": lambda x: isinstance(x, datetime),
        }
        self._start_time = {
            "value": None,
            "validator": lambda x: isinstance(x, float),
        }
        self._unsaved_keys = {
            "value": None,
            "validator": lambda x: isinstance(x, list) and all(isinstance(y, str) for y in x),
        }
        self.allow_val_change = {
            "value": None,
            "validator": lambda x: isinstance(x, bool),
        }
        self.anonymous = {
            "value": None,
            "validator": [
                lambda x: isinstance(x, str),
                self._validate_anonymous
            ],
        }
        self.api_key = {
            "value": None,
            # do not preprocess api_key: as @kptkin says, it's like changing the password
            "validator": [
                lambda x: isinstance(x, str)
            ],
        }
        self.base_url = {
            "value": "https://api.wandb.ai",
            "preprocessor": lambda x: str(x).rstrip("/"),
            "validator": [
                lambda x: isinstance(x, str),
                self._validate_base_url,
            ],
            "help": "The base url for the wandb api.",
        }
        self.code_dir = {
            "value": None,
            "validator": lambda x: isinstance(x, str),
        }
        self.config_paths = {
            "value": None,
            "validator": lambda x: isinstance(x, list) and all(isinstance(y, str) for y in x),
        }
        self.console = {
            "value": "auto",
            "validator": [
                lambda x: isinstance(x, str),
                self._validate_console,
            ],
        }
        self.disable_code = {
            "value": None,
            "validator": lambda x: isinstance(x, bool),
            "is_priority": True,
        }
        self.disable_git = {
            "value": None,
            "validator": lambda x: isinstance(x, bool),
            "is_priority": True,
        }
        self.disabled = {
            "value": False,
            "validator": lambda x: isinstance(x, bool),
            "help": "Alias for mode=dryrun, not supported yet",
        }
        self.docker = {
            "value": None,
            "validator": lambda x: isinstance(x, str),
        }
        self.email = {
            "value": "False",
            "validator": lambda x: isinstance(x, str),
        }
        self.entity = {
            "value": None,
            "validator": lambda x: isinstance(x, str),
        }
        self.files_dir_spec = {
            "value": "files",
            "validator": lambda x: isinstance(x, str),
            "hook": lambda x: os.path.join(self.wandb_dir, f"{self.run_mode}-{self.timespec}-{self.run_id}", x),
        }
        self.force = {
            "value": None,
            "validator": lambda x: isinstance(x, bool),
        }
        self.git_remote = {
            "value": "origin",
            "validator": lambda x: isinstance(x, str),
        }
        self.heartbeat_seconds = {
            "value": 30,
            "validator": lambda x: isinstance(x, int),
        }
        self.host = {
            "value": None,
            "validator": lambda x: isinstance(x, str),
        }
        self.ignore_globs = {
            "value": tuple(),
            "validator": lambda x: isinstance(x, Sequence),
        }
        self.label_disable = {
            "value": None,
            "validator": lambda x: isinstance(x, bool),
        }
        self.launch = {
            "value": None,
            "validator": lambda x: isinstance(x, bool),
        }
        self.launch_config_path = {
            "value": None,
            "validator": lambda x: isinstance(x, str),
        }
        self.log_dir_spec = {
            "value": "logs",
            "validator": lambda x: isinstance(x, str),
            "hook": lambda x: os.path.join(self.wandb_dir, f"{self.run_mode}-{self.timespec}-{self.run_id}", x),
        }
        self.log_internal_spec = {
            "value": "debug-internal.log",
            "validator": lambda x: isinstance(x, str),
        }
        self.log_symlink_internal_spec = {
            "value": "debug-internal.log",
            "validator": lambda x: isinstance(x, str),
            "hook": lambda x: os.path.join(self.wandb_dir, x),
        }
        self.log_symlink_user_spec = {
            "value": "debug.log",
            "validator": lambda x: isinstance(x, str),
            "hook": lambda x: os.path.join(self.wandb_dir, x),
        }
        self.log_user_spec = {
            "value": "debug.log",
            "validator": lambda x: isinstance(x, str),
        }
        self.login_timeout = {
            "value": None,
            "preprocessor": lambda x: float(x),
            "validator": lambda x: isinstance(x, float),
        }
        self.magic = {
            "value": None,
            "validator": lambda x: isinstance(x, str) or isinstance(x, bool) or isinstance(x, Dict),
        }
        self.mode = {
            "value": "online",
            "validator": [
                lambda x: isinstance(x, str),
                self._validate_mode,
            ],
        }
        self.notebook_name = {
            "value": None,
            "validator": lambda x: isinstance(x, str),
        }
        self.problem = {
            "value": "fatal",
            "validator": [
                lambda x: isinstance(x, str),
                self._validate_problem
            ],
        }
        self.program = {
            "value": None,
            "validator": lambda x: isinstance(x, str),
        }
        self.program_relpath = {
            "value": None,
            "validator": lambda x: isinstance(x, str),
        }
        self.project = {
            "value": None,
            "validator": [
                lambda x: isinstance(x, str),
                self._validate_project,
            ],
        }
        self.quiet = {
            "value": None,
            "preprocessor": _str_as_bool,
            "validator": lambda x: isinstance(x, bool),
        }
        self.reinit = {
            "value": None,
            "validator": lambda x: isinstance(x, bool),
        }
        self.relogin = {
            "value": None,
            "validator": lambda x: isinstance(x, bool),
        }
        self.resume = {
            "value": None,
            "validator": lambda x: isinstance(x, str),
        }
        self.resume_fname_spec = {
            "value": "wandb-resume.json",
            "validator": lambda x: isinstance(x, str),
            "hook": lambda x: os.path.join(self.wandb_dir, x),
        }
        self.root_dir = {
            "value": None,
            "validator": lambda x: isinstance(x, str),
        }
        self.run_group = {
            "value": None,
            "validator": lambda x: isinstance(x, str),
        }
        self.run_id = {
            "value": None,
            "validator": lambda x: isinstance(x, str),
        }
        self.run_job_type = {  # TODO(jhr): Audit this
            "value": None,
            "validator": lambda x: isinstance(x, str),
        }
        self.run_name = {
            "value": None,
            "validator": lambda x: isinstance(x, str),
        }
        self.run_notes = {
            "value": None,
            "validator": lambda x: isinstance(x, str),
        }
        self.run_tags = {
            "value": None,
            "validator": lambda x: isinstance(x, tuple),
        }
        self.sagemaker_disable = {
            "value": None,
            "validator": lambda x: isinstance(x, bool),
        }
        self.save_code = {
            "value": None,
            "validator": lambda x: isinstance(x, bool),
            "is_priority": True,
        }
        self.settings_system_spec = {
            "value": "~/.config/wandb/settings",
            "validator": lambda x: isinstance(x, str),
        }
        self.settings_workspace_spec = {
            "value": "settings",
            "validator": lambda x: isinstance(x, str),
            "hook": lambda x: os.path.join(self.wandb_dir, x),
        }
        self.show_colors = {
            "value": None,
            "validator": lambda x: isinstance(x, bool),
        }
        self.show_emoji = {
            "value": None,
            "validator": lambda x: isinstance(x, bool),
        }
        self.show_errors = {
            "value": "True",
            "preprocessor": _str_as_bool,
            "validator": lambda x: isinstance(x, bool),
        }
        self.show_info = {
            "value": "True",
            "preprocessor": _str_as_bool,
            "validator": lambda x: isinstance(x, bool),
        }
        self.show_warnings = {
            "value": "True",
            "preprocessor": _str_as_bool,
            "validator": lambda x: isinstance(x, bool),
        }
        self.silent = {
            "value": "False",
            "preprocessor": _str_as_bool,
            "validator": lambda x: isinstance(x, bool),
        }
        self.start_method = {
            "value": None,
            "validator": [
                lambda x: isinstance(x, str),
                self._validate_start_method,
            ],
        }
        self.strict = {
            "value": None,
            "preprocessor": _str_as_bool,
            "validator": lambda x: isinstance(x, bool),
        }
        self.summary_errors = {
            "value": None,
            "validator": lambda x: isinstance(x, int),
        }
        self.summary_warnings = {
            "value": 5,
            "preprocessor": lambda x: int(x),
            "validator": lambda x: isinstance(x, int),
            "is_policy": True,
        }
        self.sweep_id = {
            "value": None,
            "validator": lambda x: isinstance(x, str),
        }
        self.sweep_param_path = {
            "value": None,
            "validator": lambda x: isinstance(x, str),
        }
        self.symlink = {
            "value": None,
            "validator": lambda x: isinstance(x, bool),  # probed
        }
        self.sync_dir_spec = {
            "value": None,
            "validator": lambda x: isinstance(x, str),
            "hook": [
                lambda x: os.path.join(self.wandb_dir, f"{self.run_mode}-{self.timespec}-{self.run_id}")
            ],
        }
        self.sync_file_spec = {
            "value": None,
            "validator": lambda x: isinstance(x, str),
            "hook": lambda x: f"run-{self.run_id}.wandb",
        }
        self.sync_symlink_latest_spec = {
            "value": "latest-run",
            "validator": lambda x: isinstance(x, str),
            "hook": lambda x: os.path.join(self.wandb_dir, x),
        }
        self.system_sample = {
            "value": 15,
            "validator": lambda x: isinstance(x, int),
        }
        self.system_sample_seconds = {
            "value": 2,
            "validator": lambda x: isinstance(x, int),
        }
        self.tmp_dir_spec = {
            "value": "tmp",
            "validator": lambda x: isinstance(x, str),
            "hook": lambda x: os.path.join(self.wandb_dir, f"{self.run_mode}-{self.timespec}-{self.run_id}", x),
        }
        self.username = {
            "value": None,
            "validator": lambda x: isinstance(x, str),
        }

        # fixme: debug
        self.lol_id = {
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

    def update(self, settings: Dict[str, Any], source: int = Source.OVERRIDE) -> None:
        """Update individual settings using the Property.update() method."""
        if "_Settings__frozen" in self.__dict__ and self.__frozen:
            raise TypeError(f"Settings object is frozen")
        if TYPE_CHECKING:
            _source = cast(Optional[int], source)
        for key, value in settings.items():
            # only allow updating known Properties
            if key not in self.__dict__ or not isinstance(self.__dict__[key], Property):
                raise KeyError(f"Unknown setting: {key}")
            self.__dict__[key].update(value, source)

    def freeze(self) -> None:
        object.__setattr__(self, "_Settings__frozen", True)

    def unfreeze(self) -> None:
        object.__setattr__(self, "_Settings__frozen", False)

    def make_static(self) -> Dict[str, Any]:
        """Generate a static, serializable version of the settings."""
        return {k: v.value for k, v in self.__dict__.items() if isinstance(v, Property)}

    # computed properties
    @property
    def wandb_dir(self) -> str:
        return get_wandb_dir(self.root_dir or "")

    @property
    def _offline(self) -> bool:
        if self.disabled or (self.mode in ("dryrun", "offline")):
            return True
        return False

    @property
    def _noop(self) -> bool:
        return self.mode == "disabled"

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
    def _windows(self) -> bool:
        return platform.system() == "Windows"

    @property
    def _console(self) -> SettingsConsole:
        convert_dict: Dict[str, SettingsConsole] = dict(
            off=SettingsConsole.OFF,
            wrap=SettingsConsole.WRAP,
            redirect=SettingsConsole.REDIRECT,
        )
        console: str = str(self.console)
        if console == "auto":
            if self._jupyter:
                console = "wrap"
            elif self.start_method == "thread":
                console = "wrap"
            elif self._require_service:
                console = "wrap"
            elif self._windows:
                console = "wrap"
            else:
                console = "redirect"
        convert: SettingsConsole = convert_dict[console]
        return convert

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
