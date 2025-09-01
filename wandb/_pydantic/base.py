"""Base classes and other customizations for generated pydantic types."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, ClassVar, Literal

from pydantic import BaseModel, ConfigDict
from typing_extensions import TypedDict, Unpack, override

from .v1_compat import PydanticCompatMixin

if TYPE_CHECKING:
    from pydantic.main import IncEx


class DumpKwargs(TypedDict, total=False):
    """Shared keyword arguments for `BaseModel.model_{dump,dump_json}`."""

    include: IncEx | None
    exclude: IncEx | None
    context: dict[str, Any] | None
    by_alias: bool | None
    exclude_unset: bool
    exclude_defaults: bool
    exclude_none: bool
    round_trip: bool
    warnings: bool | Literal["none", "warn", "error"]
    fallback: Callable[[Any], Any] | None
    serialize_as_any: bool


# ---------------------------------------------------------------------------
# Base models and mixin classes.
#
# Extra info is provided for devs in inline comments, NOT docstrings.  This
# prevents it from showing up in generated docs for subclasses.


# FOR INTERNAL USE ONLY: v1-compatible drop-in replacement for `pydantic.BaseModel`.
# If pydantic v2 is detected, this is just `pydantic.BaseModel`.
#
# Deliberately inherits ALL default configuration from `pydantic.BaseModel`.
class CompatBaseModel(PydanticCompatMixin, BaseModel):
    __doc__ = None  # Prevent subclasses from inheriting the BaseModel docstring


class JsonableModel(CompatBaseModel):
    # Base class with sensible default behavior for classes that need to convert to/from JSON.
    #
    # Automatically parse/serialize "raw" API data (e.g. automatically convert to/from camelCase keys):
    # - `.model_{dump,dump_json}()` should return "JSON-ready" dicts or JSON strings
    # - `.model_{validate,validate_json}()` should accept "JSON-ready" dicts or JSON strings
    #
    # Ensure round-trip serialization <-> deserialization between:
    # - `model_dump()` <-> `model_validate()`
    # - `model_dump_json()` <-> `model_validate_json()`
    #
    # These behaviors are useful for models that need to predictably handle e.g. GraphQL request/response data.

    model_config = ConfigDict(
        populate_by_name=True,  # Discouraged in v2.11+, deprecated in v3, kept for now for compatibility
        validate_by_name=True,  # Introduced in v2.11, ignored in earlier versions
        validate_by_alias=True,  # Introduced in v2.11, ignored in earlier versions
        serialize_by_alias=True,  # Introduced in v2.11, ignored in earlier versions
        from_attributes=True,
        validate_assignment=True,
        use_attribute_docstrings=True,
    )

    # Custom defaults keyword args for `BaseModel.model_{dump,dump_json}`:
    # - convert keys to JSON-ready names and objects to JSON-ready dicts
    # - ensure round-trippable result
    __DUMP_DEFAULTS: ClassVar[DumpKwargs] = DumpKwargs(by_alias=True, round_trip=True)

    @override
    def model_dump(
        self, *, mode: str = "json", **kwargs: Unpack[DumpKwargs]
    ) -> dict[str, Any]:
        kwargs = {**self.__DUMP_DEFAULTS, **kwargs}  # allows overrides, if needed
        return super().model_dump(mode=mode, **kwargs)

    @override
    def model_dump_json(
        self, *, indent: int | None = None, **kwargs: Unpack[DumpKwargs]
    ) -> str:
        kwargs = {**self.__DUMP_DEFAULTS, **kwargs}  # allows overrides, if needed
        return super().model_dump_json(indent=indent, **kwargs)


# Base class for all GraphQL-generated types.
class GQLBase(JsonableModel):
    model_config = ConfigDict(
        validate_default=True,
        revalidate_instances="always",
        protected_namespaces=(),  # Some GraphQL fields may begin with "model_"
    )
