"""Base classes and other customizations for generated pydantic types."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Final, Literal

from pydantic import BaseModel, ConfigDict
from typing_extensions import TypedDict, Unpack, override

from .v1_compat import PydanticCompatMixin

if TYPE_CHECKING:
    from pydantic.main import IncEx


class ModelDumpKwargs(TypedDict, total=False):
    """Common keyword arguments for `BaseModel.model_{dump,dump_json}`."""

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
# Extra dev context is deliberately provided in inline comments, NOT docstrings,
# so it does not show up in generated docs for subclasses.


# Pydantic v1-compatible base class for internally-defined pydantic types.
# Deliberately avoids any modifications to the default behavior of `BaseModel`.
# NOTE: If pydantic v2 is detected, this should behave like a regular `BaseModel`.
class CompatBaseModel(PydanticCompatMixin, BaseModel):
    __doc__ = None  # Prevent subclasses from inheriting the BaseModel docstring


# Custom overrides for default `BaseModel.model_dump/model_dump_json` behavior, i.e.
# - convert to JSON-ready dicts/schema-valid JSON by default, including converted field names
# - ensure round-trippable result
DUMP_DEFAULT_KWS: Final[ModelDumpKwargs] = dict(by_alias=True, round_trip=True)


class JsonableModel(CompatBaseModel):
    # Base class for models where we want:
    #
    # - Basic automatic handling of "raw" API data, e.g. to/from schemas with camelCase fields:
    #   - `model_dump()/model_dump_json()` to convert to API-ready JSON(-able) data
    #   - `model_validate()/model_validate_json()` to convert from raw API data
    # - Round-trip serialization <-> deserialization behavior between:
    #   - `model_dump()` <-> `model_validate()`
    #   - `model_dump_json()` <-> `model_validate_json()` (if available)
    #
    # This is useful for models that need to predictably handle input/output JSON data for APIs (e.g. the wandb backend).

    model_config = ConfigDict(
        populate_by_name=True,  # Discouraged in v2.11+, deprecated in v3, kept for now for compatibility
        validate_by_name=True,  # Introduced in v2.11, ignored in earlier versions
        validate_by_alias=True,  # Introduced in v2.11, ignored in earlier versions
        serialize_by_alias=True,  # Introduced in v2.11, ignored in earlier versions
    )

    @override
    def model_dump(
        self,
        *,
        mode: Literal["json", "python"] | str = "json",
        **kwargs: Unpack[ModelDumpKwargs],
    ) -> dict[str, Any]:
        kwargs = {**DUMP_DEFAULT_KWS, **kwargs}  # allow user to override defaults
        return super().model_dump(mode=mode, **kwargs)

    @override
    def model_dump_json(
        self, *, indent: int | None = None, **kwargs: Unpack[ModelDumpKwargs]
    ) -> str:
        kwargs = {**DUMP_DEFAULT_KWS, **kwargs}  # allow user to override defaults
        return super().model_dump_json(indent=indent, **kwargs)


# Base class for all GraphQL-generated types.
class GQLBase(JsonableModel):
    model_config = ConfigDict(
        from_attributes=True,
        validate_assignment=True,
        validate_default=True,
        use_attribute_docstrings=True,
        revalidate_instances="always",
        protected_namespaces=(),  # Some GraphQL fields may begin with "model_"
    )
