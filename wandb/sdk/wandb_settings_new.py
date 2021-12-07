import enum
from typing import (
    Any,
    Callable,
    Dict,
    Optional,
    Sequence,
)

import attr


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
    def __init__(
        self,
        name: str,
        value: Optional[Any] = None,
        preprocessor: Optional[Sequence[Callable]] = tuple(),
        validator: Optional[Sequence[Callable]] = tuple(),
        is_policy: bool = False,
        frozen: bool = False,
        source: int = Source.BASE,

    ):
        self.name = name
        self._preprocessor = preprocessor
        self._validator = validator
        self._is_policy = is_policy
        self._source = source

        # preprocess and validate value
        self.__dict__["value"] = self._validate(self._preprocess(value))

        self.__frozen = frozen

    def _preprocess(self, value):
        for p in self._preprocessor:
            value = p(value)
        return value

    def _validate(self, value):
        for v in self._validator:
            if not v(value):
                raise ValueError(f"Invalid value for property {self.name}: {value}")
        return value

    def update(
        self,
        value: Optional[Any] = None,
        source: Optional[int] = Source.OVERRIDE,
    ):
        if self.__frozen:
            raise TypeError("Property object is frozen")
        # - always update value if source == Source.OVERRIDE
        # - if not previously overridden:
        #   - update value if source is lower than or equal to current source and property is policy
        #   - update value if source is higher than or equal to current source and property is not policy
        if (
            (source == Source.OVERRIDE)
            or (self._is_policy and self._source != Source.OVERRIDE and source <= self._source)
            or (not self._is_policy and self._source != Source.OVERRIDE and source >= self._source)
        ):
            self.__dict__["value"] = self._validate(self._preprocess(value))
            self._source = source

    def __setattr__(self, key, value):
        if key == "value":
            raise AttributeError("Use update() to update property value")
        self.__dict__[key] = value

    def __repr__(self):
        # return f"<Property {self.name}: value={self.value} source={self._source}>"
        # return f"<Property {self.name}: value={self.value}>"
        # return self.__dict__.__repr__()
        return f"{self.__dict__['value']}"


@attr.s
class Settings:
    """
    Settings for the wandb client.
    """

    # base_url: str = attr.ib(
    #     default="https://api.wandb.ai",
    #     validator=[attr.validators.instance_of(str)],
    #     metadata={
    #         "source": Source.BASE,
    #         "help": "The base url for the wandb api."
    #     },
    # )
    # The base url for the wandb api.  fixme: add help string to Property instead?
    base_url = attr.ib(Property(name="base_url", value="https://api.wandb.ai", is_policy=True))
    meaning_of_life = attr.ib(Property(name="meaning_of_life", value="42", preprocessor=[lambda x: int(x)]))

    def __getattr__(self, item):
        return self.__dict__[item].value

    def __setattr__(self, key, value):
        raise TypeError("Use update() to update property values")

    def update(self):
        pass
