from datetime import datetime
import enum
import multiprocessing
from typing import (
    Any,
    Callable,
    cast,
    Dict,
    Optional,
    Sequence,
    Set,
    Tuple,
    Type,
    TYPE_CHECKING,
    Union,
)
from urllib.parse import urljoin

from wandb.errors import UsageError


def _build_inverse_map(prefix: str, d: Dict[str, Optional[str]]) -> Dict[str, str]:
    return {v or prefix + k.upper(): k for k, v in d.items()}


@enum.unique
class Source(enum.IntEnum):
    OVERRIDE: int = 0
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


@enum.unique
class SettingsConsole(enum.Enum):
    OFF = 0
    WRAP = 1
    REDIRECT = 2


class Property:
    def __init__(  # pylint: disable=unused-argument
        self,
        name: str,
        value: Optional[Any] = None,
        preprocessor: Union[Callable, Sequence[Callable], None] = None,
        validator: Union[Callable, Sequence[Callable], None] = None,
        # runtime converter (hook?): properties can be e.g. tied to other properties
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
    def value(self):
        _value = self._value
        if _value is not None and self._hook is not None:
            _hook = [self._hook] if callable(self._hook) else self._hook
            for h in _hook:
                _value = h(_value)
        return _value

    def _preprocess(self, value):
        if value is not None and self._preprocessor is not None:
            _preprocessor = [self._preprocessor] if callable(self._preprocessor) else self._preprocessor
            for p in _preprocessor:
                value = p(value)
        return value

    def _validate(self, value):
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

    __frozen: bool = False

    Console: Type[SettingsConsole] = SettingsConsole

    # helper methods for pre-processing values
    def _join_with_base_url(self, url: str) -> str:
        return urljoin(self.base_url, url)

    # helper methods for validating values
    @staticmethod
    def _validate_mode(value: str) -> bool:
        choices = {"dryrun", "run", "offline", "online", "disabled"}
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
        choices = {"auto", "redirect", "off", "wrap"}
        if value not in choices:
            raise UsageError(f"Settings field `console`: '{value}' not in {choices}")
        return True

    @staticmethod
    def _validate_problem(value: str) -> bool:
        choices = {"fatal", "warn", "silent"}
        if value not in choices:
            raise UsageError(f"Settings field `problem`: '{value}' not in {choices}")
        return True

    @staticmethod
    def _validate_anonymous(value: str) -> bool:
        choices = {"allow", "must", "never", "false", "true"}
        if value not in choices:
            raise UsageError(f"Settings field `anonymous`: '{value}' not in {choices}")
        return True

    def __init__(
        self,
        **kwargs,
    ):
        settings = {
            # former class attributes
            "mode": {
                "value": "online",
                "validator": [
                    lambda x: isinstance(x, str),
                    self._validate_mode,
                ],
            },
            "start_method": {
                "value": None,
                "validator": [
                    lambda x: isinstance(x, str),
                    self._validate_start_method,
                ],
            },
            "_require_service": {
                "value": None,
                "validator": lambda x: isinstance(x, str),
            },
            "_service_transport": {
                "value": None,
                "validator": lambda x: isinstance(x, str),
            },
            "console": {
                "value": "auto",
                "validator": [
                    lambda x: isinstance(x, str),
                    self._validate_console,
                ],
            },
            "disabled": {
                "value": False,
                "validator": lambda x: isinstance(x, bool),
            },
            "force": {
                "value": None,
                "validator": lambda x: isinstance(x, bool),
            },
            "run_tags": {
                "value": None,
                "validator": lambda x: isinstance(x, Tuple),
            },
            "run_id": {
                "value": None,
                "validator": lambda x: isinstance(x, str),
            },
            "sweep_id": {
                "value": None,
                "validator": lambda x: isinstance(x, str),
            },
            "launch": {
                "value": None,
                "validator": lambda x: isinstance(x, bool),
            },
            "launch_config_path": {
                "value": None,
                "validator": lambda x: isinstance(x, str),
            },
            "resume_fname_spec": {
                "value": None,
                "validator": lambda x: isinstance(x, str),
            },
            "root_dir": {
                "value": None,
                "validator": lambda x: isinstance(x, str),
            },
            # log_dir_spec: Optional[str] = None
            # log_user_spec: Optional[str] = None
            # log_internal_spec: Optional[str] = None
            # sync_file_spec: Optional[str] = None
            # sync_dir_spec: Optional[str] = None
            # files_dir_spec: Optional[str] = None
            # tmp_dir_spec: Optional[str] = None
            # log_symlink_user_spec: Optional[str] = None
            # log_symlink_internal_spec: Optional[str] = None
            # sync_symlink_latest_spec: Optional[str] = None
            # settings_system_spec: Optional[str] = None
            # settings_workspace_spec: Optional[str] = None
            "silent": {
                "value": "False",
                "validator": lambda x: isinstance(x, str),
            },
            "quiet": {
                "value": None,
                "validator": lambda x: isinstance(x, str) or isinstance(x, bool),
            },
            "show_info": {
                "value": "True",
                "validator": lambda x: isinstance(x, str),
            },
            "show_warnings": {
                "value": "True",
                "validator": lambda x: isinstance(x, str),
            },
            "show_errors": {
                "value": "True",
                "validator": lambda x: isinstance(x, str),
            },
            "username": {
                "value": None,
                "validator": lambda x: isinstance(x, str),
            },
            "email": {
                "value": "False",
                "validator": lambda x: isinstance(x, str),
            },
            "save_code": {
                "value": None,
                "validator": lambda x: isinstance(x, bool),
                "is_priority": True,
            },
            "disable_code": {
                "value": None,
                "validator": lambda x: isinstance(x, bool),
                "is_priority": True,
            },
            "disable_git": {
                "value": None,
                "validator": lambda x: isinstance(x, bool),
                "is_priority": True,
            },
            "git_remote": {
                "value": "origin",
                "validator": lambda x: isinstance(x, str),
            },
            "code_dir": {
                "value": None,
                "validator": lambda x: isinstance(x, str),
            },
            "program_relpath": {
                "value": None,
                "validator": lambda x: isinstance(x, str),
            },
            "program": {
                "value": None,
                "validator": lambda x: isinstance(x, str),
            },
            "notebook_name": {
                "value": None,
                "validator": lambda x: isinstance(x, str),
            },
            "host": {
                "value": None,
                "validator": lambda x: isinstance(x, str),
            },
            "resume": {
                "value": None,
                "validator": lambda x: isinstance(x, str),
            },
            "strict": {
                "value": None,
                "validator": lambda x: isinstance(x, str),
            },
            "label_disable": {
                "value": None,
                "validator": lambda x: isinstance(x, bool),
            },
            # Public attributes
            "entity": {
                "value": None,
                "validator": lambda x: isinstance(x, str),
            },
            "project": {
                "value": None,
                "validator": lambda x: isinstance(x, str),
            },
            "run_group": {
                "value": None,
                "validator": lambda x: isinstance(x, str),
            },
            "run_name": {
                "value": None,
                "validator": lambda x: isinstance(x, str),
            },
            "run_notes": {
                "value": None,
                "validator": lambda x: isinstance(x, str),
            },
            "sagemaker_disable": {
                "value": None,
                "validator": lambda x: isinstance(x, bool),
            },
            # TODO(jhr): Audit this
            "run_job_type": {
                "value": None,
                "validator": lambda x: isinstance(x, str),
            },

            # Private attributes
            "_start_time": {
                "value": None,
                "validator": lambda x: isinstance(x, float),
            },
            "_start_datetime": {
                "value": None,
                "validator": lambda x: isinstance(x, datetime),
            },
            "_unsaved_keys": {
                "value": None,
                "validator": lambda x: isinstance(x, list) and all(isinstance(y, str) for y in x),
            },
            "_except_exit": {
                "value": None,
                "validator": lambda x: isinstance(x, bool),
            },
            "_runqueue_item_id": {
                "value": None,
                "validator": lambda x: isinstance(x, str),
            },

            # former init args
            "base_url": {
                "value": "https://api.wandb.ai",
                "preprocessor": lambda x: str(x).rstrip("/"),
                "validator": lambda x: isinstance(x, str),
                "help": "The base url for the wandb api.",
            },
            "summary_warnings": {
                "value": 5,
                "preprocessor": lambda x: int(x),
                "validator": lambda x: isinstance(x, int),
                "is_policy": True,
            },
            "ignore_globs": {
                "value": tuple(),
                "validator": lambda x: isinstance(x, Sequence),
            },

            # debug args
            "lol_id": {
                "value": "abc123",
                "preprocessor": lambda x: str(x),
                "validator": lambda x: isinstance(x, str),
                "hook": lambda x: self._join_with_base_url(x),
            },
            "meaning_of_life": {
                "value": "42",
                "preprocessor": lambda x: int(x),
                "is_policy": True,  # surely the big brother knows best
            }
        }
        # update overridden defaults from kwargs
        for k, v in kwargs.items():
            if k in settings:
                settings[k]["value"] = v
        # init own attributes
        for key, specs in settings.items():
            object.__setattr__(
                self,
                key,
                Property(name=key, **specs, source=Source.SETTINGS),
            )

        # freeze settings
        # self.freeze()

    def __repr__(self):
        # return f"<Settings {[{a: p} for a, p in self.__dict__.items()]}>"
        return f"<Settings {self.__dict__}>"

    def __getattribute__(self, name: str):
        item = object.__getattribute__(self, name)
        if isinstance(item, Property):
            return item.value
        return item

    def __setattr__(self, key, value):
        raise TypeError("Use update() to update attribute values")

    @property
    def is_local(self) -> bool:
        if self.base_url is not None:
            return self.base_url != "https://api.wandb.ai"
        return False

    def update(self, settings: Dict[str, Any], source: int = Source.OVERRIDE):
        if "_Settings__frozen" in self.__dict__ and self.__frozen:
            raise TypeError(f"Settings object is frozen")
        if TYPE_CHECKING:
            _source = cast(Optional[int], source)
        for key, value in settings.items():
            self.__dict__[key].update(value, source)

    def freeze(self):
        object.__setattr__(self, "_Settings__frozen", True)

    def unfreeze(self):
        object.__setattr__(self, "_Settings__frozen", False)

    def make_static(self):
        return {k: v.value for k, v in self.__dict__.items() if isinstance(v, Property)}
