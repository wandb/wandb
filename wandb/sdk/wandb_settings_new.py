import enum
from typing import (
    Any,
    Callable,
    cast,
    Dict,
    Optional,
    Sequence,
    TYPE_CHECKING,
    Union,
)
from urllib.parse import urljoin


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
        if self._hook is not None:
            _hook = [self._hook] if callable(self._hook) else self._hook
            for h in _hook:
                _value = h(_value)
        return _value

    def _preprocess(self, value):
        if self._preprocessor is not None:
            _preprocessor = [self._preprocessor] if callable(self._preprocessor) else self._preprocessor
            for p in _preprocessor:
                value = p(value)
        return value

    def _validate(self, value):
        if self._validator is not None:
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
        return f"<Property {self.name}: value={self.value} source={self._source}>"
        # return f"<Property {self.name}: value={self._value}>"
        # return self.__dict__.__repr__()
        # return f"{self._value}"


class Settings:
    """
    Settings for the wandb client.
    """

    __frozen: bool = False

    def _join_with_base_url(self, url):
        return urljoin(self.base_url, url)

    def __init__(
        self,
        **kwargs,
    ):
        settings = {
            "base_url": {
                "value": "https://api.wandb.ai",
                "preprocessor": lambda x: str(x),
                "validator": lambda x: isinstance(x, str),
                "is_policy": True,
                "help": "The base url for the wandb api.",
            },
            "run_id": {
                "value": "abc123",
                "preprocessor": lambda x: str(x),
                "validator": lambda x: isinstance(x, str),
                "hook": lambda x: self._join_with_base_url(x),
            },
            "meaning_of_life": {
                "value": "42",
                "preprocessor": lambda x: int(x),
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
        return f"<Settings {[{a: p} for a, p in self.__dict__.items()]}>"

    def __getattribute__(self, name: str):
        item = object.__getattribute__(self, name)
        if isinstance(item, Property):
            return item.value
        return item

    def __setattr__(self, key, value):
        raise TypeError("Use update() to update attribute values")

    # def _path_convert(self, *path: Any) -> Optional[str]:
    #     """convert slashes, expand ~ and other macros."""
    #
    #     format_dict: Dict[str, Union[str, int]] = dict()
    #     if self._start_time and self._start_datetime:
    #         format_dict["timespec"] = datetime.strftime(
    #             self._start_datetime, "%Y%m%d_%H%M%S"
    #         )
    #     if self.run_id:
    #         format_dict["run_id"] = self.run_id
    #     format_dict["run_mode"] = "offline-run" if self._offline else "run"
    #     format_dict["proc"] = os.getpid()
    #     # TODO(cling): hack to make sure we read from local settings
    #     #              this is wrong if the run_dir changes later
    #     format_dict["wandb_dir"] = self.wandb_dir or "wandb"
    #
    #     path_items: List[str] = []
    #     for p in path:
    #         part = self._path_convert_part(p, format_dict)
    #         if part is None:
    #             return None
    #         path_items += part
    #     converted_path = os.path.join(*path_items)
    #     converted_path = os.path.expanduser(converted_path)
    #     return converted_path

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
