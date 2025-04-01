"""Provides partial support for compatibility with Pydantic v1."""

from __future__ import annotations

import sys
from importlib.metadata import version
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    ClassVar,
    Literal,
    Mapping,
    TypeVar,
    overload,
)

import pydantic
from typing_extensions import ParamSpec

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


PYTHON_VERSION = sys.version_info

pydantic_major_version, *_ = version(pydantic.__name__).split(".")
IS_PYDANTIC_V2: bool = int(pydantic_major_version) >= 2


ModelT = TypeVar("ModelT")
RT = TypeVar("RT")
P = ParamSpec("P")


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


# Pydantic BaseModels are defined with a custom metaclass, but its namespace
# has changed between pydantic versions.
#
# In v1, it can be imported as `from pydantic.main import ModelMetaclass`
# In v2, it's defined in an internal module so we avoid directly importing it.
PydanticModelMetaclass: type = type(pydantic.BaseModel)


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

    # note: workarounds to patch "class properties" aren't consistent between python
    # versions, so this will have to do until changes are needed.
    if not ((3, 9) <= PYTHON_VERSION < (3, 13)):

        @property
        def model_fields(self) -> dict[str, Any]:
            return self.__fields__


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

    # workarounds to patch "class properties" aren't consistent between python
    # versions, so this will have to do until changes are needed.
    if (3, 9) <= PYTHON_VERSION < (3, 13):

        @classmethod  # type: ignore[misc]
        @property
        def model_fields(cls: type[V1Model]) -> Mapping[str, Any]:
            return cls.__fields__

    @property
    def model_fields_set(self: V1Model) -> set[str]:
        return self.__fields_set__


# Placeholder. Pydantic v2 is already compatible with itself, so no need for extra mixins.
class V2Mixin:
    pass


# Pick the mixin type based on the detected Pydantic version.
PydanticCompatMixin: type = V2Mixin if IS_PYDANTIC_V2 else V1Mixin


# ----------------------------------------------------------------------------
# Decorators and other pydantic helpers
# ----------------------------------------------------------------------------
if IS_PYDANTIC_V2:
    field_validator = pydantic.field_validator
    model_validator = pydantic.model_validator
    AliasChoices = pydantic.AliasChoices
    computed_field = pydantic.computed_field

else:
    # Redefines `@field_validator` with a v2-like signature
    # to call `@validator` from v1 instead.
    def field_validator(
        field: str,
        /,
        *fields: str,
        mode: Literal["before", "after", "wrap", "plain"] = "after",
        check_fields: bool | None = None,
        **_: Any,
    ) -> Callable:
        return pydantic.validator(
            field,
            *fields,
            pre=(mode == "before"),
            always=True,
            check_fields=bool(check_fields),
            allow_reuse=True,
        )

    # Redefines `@model_validator` with a v2-like signature
    # to call `@root_validator` from v1 instead.
    def model_validator(
        *,
        mode: Literal["before", "after", "wrap", "plain"],
        **_: Any,
    ) -> Callable:
        if mode == "after":
            # Patch the behavior for `@model_validator(mode="after")` in v1.  This is
            # necessarily complicated because:
            # - `@model_validator(mode="after")` decorates an instance method in pydantic v2
            # - `@root_validator(pre=False)` always decorates a classmethod in pydantic v1
            def _decorator(v2_method: Callable) -> Any:
                def v1_method(
                    cls: type[V1Model], values: dict[str, Any]
                ) -> dict[str, Any]:
                    # Note: Since this is an "after" validator, the values should already be
                    # validated, so `.construct()` in v1 (`.model_construct()` in v2)
                    # should create a valid object to pass to the **original** decorated instance method.
                    validated = v2_method(cls.construct(**values))

                    # Pydantic v1 expects the validator to return a dict of {field_name -> value}
                    return {
                        name: getattr(validated, name) for name in validated.__fields__
                    }

                return pydantic.root_validator(pre=False, allow_reuse=True)(  # type: ignore[call-overload]
                    classmethod(v1_method)
                )

            return _decorator
        else:
            return pydantic.root_validator(pre=(mode == "before"), allow_reuse=True)  # type: ignore[call-overload]

    @overload  # type: ignore[no-redef]
    def computed_field(func: Callable | property, /) -> property: ...
    @overload
    def computed_field(
        func: None, /, **_: Any
    ) -> Callable[[Callable | property], property]: ...

    def computed_field(
        func: Callable | property | None = None, /, **_: Any
    ) -> property | Callable[[Callable | property], property]:
        """Compatibility wrapper for Pydantic v2's `computed_field` in v1."""

        def always_property(f: Callable | property) -> property:
            # Convert the method to a property only if needed
            return f if isinstance(f, property) else property(f)

        # Handle both decorator styles
        return always_property if (func is None) else always_property(func)

    class AliasChoices:  # type: ignore [no-redef]
        """Placeholder class for Pydantic v2's AliasChoices for partial v1 compatibility."""

        aliases: list[str]

        def __init__(self, *aliases: str):
            self.aliases = list(aliases)
