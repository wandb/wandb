"""Base classes and other customizations for generated pydantic types."""

from __future__ import annotations

from abc import ABC
from typing import TYPE_CHECKING, Any, Callable, ClassVar, Literal, overload

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from typing_extensions import TypedDict, Unpack, override

if TYPE_CHECKING:
    from pydantic.main import IncEx


class ModelDumpKwargs(TypedDict, total=False):
    """Shared keyword arguments for `BaseModel.model_{dump,dump_json}`.

    Newer pydantic versions may accept more arguments than are listed here.
    Last updated for pydantic v2.12.0.
    """

    include: IncEx | None
    exclude: IncEx | None
    context: Any | None
    by_alias: bool | None
    exclude_unset: bool
    exclude_defaults: bool
    exclude_none: bool
    exclude_computed_fields: bool
    round_trip: bool
    warnings: bool | Literal["none", "warn", "error"]
    fallback: Callable[[Any], Any] | None
    serialize_as_any: bool


# ---------------------------------------------------------------------------
# Base models and mixin classes
# ---------------------------------------------------------------------------


class JsonableModel(BaseModel, ABC):
    """Base class with sensible defaults for converting to and from JSON.

    Automatically parse or serialize "raw" API data (e.g. convert to and from
    camelCase keys):
    - `.model_{dump,dump_json}()` should return JSON-ready dicts or JSON
      strings.
    - `.model_{validate,validate_json}()` should accept JSON-ready dicts or
      JSON strings.

    Ensure round-trip serialization <-> deserialization between:
    - `model_dump()` <-> `model_validate()`
    - `model_dump_json()` <-> `model_validate_json()`

    These behaviors help models predictably handle GraphQL request or response
    data.

    <!-- lazydoc-ignore: internal -->
    """

    model_config = ConfigDict(
        # ---------------------------------------------------------------------------
        # Discouraged in v2.11+, deprecated in v3. Kept here for compatibility.
        populate_by_name=True,
        # ---------------------------------------------------------------------------
        # Introduced in v2.11, ignored in earlier versions
        validate_by_name=True,
        validate_by_alias=True,
        serialize_by_alias=True,
        # ---------------------------------------------------------------------------
        validate_assignment=True,
        use_attribute_docstrings=True,
        from_attributes=True,
    )

    # Custom default kwargs for `JsonableModel.model_{dump,dump_json}`:
    # - by_alias: Convert keys to JSON-ready names and objects to JSON-ready
    #   dicts.
    # - round_trip: Ensure the result can round-trip.
    __DUMP_DEFAULTS: ClassVar[dict[str, Any]] = dict(by_alias=True, round_trip=True)

    @overload  # Actual signature
    def model_dump(
        self, *, mode: str, **kwargs: Unpack[ModelDumpKwargs]
    ) -> dict[str, Any]: ...
    @overload  # In case pydantic adds more kwargs in future releases
    def model_dump(self, **kwargs: Any) -> dict[str, Any]: ...

    @override
    def model_dump(self, *, mode: str = "json", **kwargs: Any) -> dict[str, Any]:
        kwargs = {**self.__DUMP_DEFAULTS, **kwargs}  # allows overrides, if needed
        return super().model_dump(mode=mode, **kwargs)

    @overload  # Actual signature
    def model_dump_json(
        self, *, indent: int | None, **kwargs: Unpack[ModelDumpKwargs]
    ) -> str: ...
    @overload  # In case pydantic adds more kwargs in future releases
    def model_dump_json(self, **kwargs: Any) -> str: ...

    @override
    def model_dump_json(self, *, indent: int | None = None, **kwargs: Any) -> str:
        kwargs = {**self.__DUMP_DEFAULTS, **kwargs}  # allows overrides, if needed
        return super().model_dump_json(indent=indent, **kwargs)


# Base class for all GraphQL-derived types.
class GQLBase(JsonableModel, ABC):
    model_config = ConfigDict(
        validate_default=True,
        revalidate_instances="always",
        protected_namespaces=(),  # Some GraphQL fields may begin with "model_"
    )


# Base class for GraphQL result types, i.e. parsed GraphQL response data.
class GQLResult(GQLBase, ABC):
    model_config = ConfigDict(
        alias_generator=to_camel,  # Assume JSON names are camelCase, by default
        frozen=True,  # Keep the actual response data immutable
    )


# Base class for GraphQL input types, i.e. prepared variables or input objects
# for queries and mutations.
class GQLInput(GQLBase, ABC):
    # For GraphQL inputs, exclude null values when preparing JSON-able request
    # data.
    __DUMP_DEFAULTS: ClassVar[dict[str, Any]] = dict(exclude_none=True)

    @override
    def model_dump(self, *, mode: str = "json", **kwargs: Any) -> dict[str, Any]:
        kwargs = {**self.__DUMP_DEFAULTS, **kwargs}
        return super().model_dump(mode=mode, **kwargs)

    @override
    def model_dump_json(self, *, indent: int | None = None, **kwargs: Any) -> str:
        kwargs = {**self.__DUMP_DEFAULTS, **kwargs}
        return super().model_dump_json(indent=indent, **kwargs)
