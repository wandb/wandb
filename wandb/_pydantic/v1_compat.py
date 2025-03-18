"""Provides partial support for compatibility with Pydantic v1."""

from __future__ import annotations

from importlib.metadata import version
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    ClassVar,
    Generic,
    Mapping,
    TypeVar,
    overload,
)

import pydantic

if TYPE_CHECKING:
    from typing import Protocol

    class V1Model(Protocol):
        __config__: ClassVar[type]
        __fields__: ClassVar[dict[str, Any]]
        __fields_set__: set[str]

        @classmethod
        def update_forward_refs(cls, *args: Any, **kwargs: Any) -> None: ...
        @classmethod
        def construct(cls, *args: Any, **kwargs: Any) -> V1Model: ...
        @classmethod
        def parse_obj(cls, *args: Any, **kwargs: Any) -> V1Model: ...
        @classmethod
        def parse_raw(cls, *args: Any, **kwargs: Any) -> V1Model: ...
        def dict(self, *args: Any, **kwargs: Any) -> dict[str, Any]: ...
        def json(self, *args: Any, **kwargs: Any) -> str: ...
        def copy(self, *args: Any, **kwargs: Any) -> V1Model: ...


pydantic_major_version, *_ = version(pydantic.__name__).split(".")
IS_PYDANTIC_V2: bool = int(pydantic_major_version) >= 2


ModelT = TypeVar("ModelT")
RT = TypeVar("RT")


# Maps {v2 -> v1} model config keys that were renamed in v2.
# See: https://docs.pydantic.dev/latest/migration/#changes-to-config
_V1_CONFIG_KEYS = {
    "populate_by_name": "allow_population_by_field_name",
    "str_to_lower": "anystr_lower",
    "str_strip_whitespace": "anystr_strip_whitespace",
    "str_to_upper": "anystr_upper",
    "ignored_types": "keep_untouched",
    "str_max_length": "max_anystr_length",
    "str_min_length": "min_anystr_length",
    "from_attributes": "orm_mode",
    "json_schema_extra": "schema_extra",
    "validate_default": "validate_all",
}


def _convert_v2_config(v2_config: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of the v2 ConfigDict with renamed v1 keys."""
    return {_V1_CONFIG_KEYS.get(k, k): v for k, v in v2_config.items()}


PydanticModelMetaclass: type
if IS_PYDANTIC_V2:
    PydanticModelMetaclass = type  # placeholder
else:
    import pydantic.main

    # NOTE: the `pydantic.main.ModelMetaclass` namespace is only in pydantic V1
    PydanticModelMetaclass = pydantic.main.ModelMetaclass


class V1MixinMetaclass(PydanticModelMetaclass):
    def __new__(
        cls,
        name: str,
        bases: tuple[type, ...],
        namespace: dict[str, Any],
        **kwargs: Any,
    ):
        # Converts a `model_config` dict in a V2 class definition, e.g.:
        #
        #     class MyModel(BaseModel):
        #         model_config = ConfigDict(populate_by_name=True)
        #
        # ...to a `Config` class in a V1 class definition, e.g.:
        #
        #     class MyModel(BaseModel):
        #         class Config:
        #             allow_population_by_field_name = True
        #
        if config_dict := namespace.pop("model_config", None):
            namespace["Config"] = type("Config", (), _convert_v2_config(config_dict))
        return super().__new__(cls, name, bases, namespace, **kwargs)


class classproperty(Generic[ModelT, RT]):  # noqa: N801
    """Exposes the decorated class method as a "class property".

    Needed in Pydantic v1 environments to simulate Pydantic v2 behavior of:
    - BaseModel.model_fields
    """

    def __init__(self, fget: Callable[[type[ModelT]], RT], /):
        self.fget = fget  # fget should be a classmethod as well

    @overload
    def __get__(self, instance: None, objtype: type[ModelT]) -> RT: ...
    @overload
    def __get__(self, instance: ModelT, objtype: type[ModelT]) -> RT: ...
    def __get__(self, instance: ModelT | None, objtype: type[ModelT]) -> RT:
        return self.fget.__get__(instance, objtype)()


# Mixin to ensure compatibility of Pydantic models if Pydantic v1 is detected.
# These are "best effort" implementations and cannot guarantee complete
# compatibility in v1 environments.
#
# Whenever possible, users should strongly prefer upgrading to Pydantic v2 to
# ensure full compatibility.
class V1Mixin(metaclass=V1MixinMetaclass):
    @classmethod
    def __try_update_forward_refs__(cls: type[V1Model], **localns: Any) -> None:
        if hasattr(sup := super(), "__try_update_forward_refs__"):
            sup.__try_update_forward_refs__(**localns)

    @classmethod
    def model_rebuild(cls, *args: Any, **kwargs: Any) -> None:
        return cls.update_forward_refs(*args, **kwargs)

    @classmethod
    def model_construct(cls, *args: Any, **kwargs: Any) -> V1Model:
        return cls.construct(*args, **kwargs)

    @classmethod
    def model_validate(cls, *args: Any, **kwargs: Any) -> V1Model:
        return cls.parse_obj(*args, **kwargs)

    @classmethod
    def model_validate_json(cls, *args: Any, **kwargs: Any) -> V1Model:
        return cls.parse_raw(*args, **kwargs)

    def model_dump(self: V1Model, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.dict(*args, **kwargs)

    def model_dump_json(self: V1Model, *args: Any, **kwargs: Any) -> str:
        return self.json(*args, **kwargs)

    def model_copy(self: V1Model, *args: Any, **kwargs: Any) -> V1Model:
        return self.copy(*args, **kwargs)

    @classmethod
    @classproperty
    def model_fields(cls) -> Mapping[str, Any]:
        return cls.__fields__

    @property
    def model_fields_set(self: type[V1Model]) -> set[str]:
        return self.__fields_set__


# Placeholder. Pydantic v2 is already compatible with itself, so no need for extra mixins.
class V2Mixin:
    pass


# Pick the mixin type based on the detected Pydantic version.
PydanticCompatMixin: type = V2Mixin if IS_PYDANTIC_V2 else V1Mixin
