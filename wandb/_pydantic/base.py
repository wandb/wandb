"""Base classes and other customizations for generated pydantic types."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, Json
from typing_extensions import Annotated, TypedDict, Unpack, override

from .v1_compat import PydanticCompatMixin

if TYPE_CHECKING:
    from pydantic.main import IncEx


class ModelDumpKwargs(TypedDict, total=False):
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


#: Custom overrides of default kwargs for `BaseModel.model_{dump,dump_json}`.
MODEL_DUMP_DEFAULTS = ModelDumpKwargs(
    by_alias=True,  # Always serialize with aliases (e.g. camelCase names)
    round_trip=True,  # Ensure serialized values remain valid inputs for deserialization
)


# Base class for all generated classes/types.
# Omitted from docstring to avoid inclusion in generated docs.
class Base(PydanticCompatMixin, BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        validate_assignment=True,
        validate_default=True,
        extra="forbid",
        use_attribute_docstrings=True,
        from_attributes=True,
        revalidate_instances="always",
    )

    @override
    def model_dump(
        self,
        *,
        mode: Literal["json", "python"] | str = "json",  # NOTE: changed default
        **kwargs: Unpack[ModelDumpKwargs],
    ) -> dict[str, Any]:
        kwargs = {**MODEL_DUMP_DEFAULTS, **kwargs}
        return super().model_dump(mode=mode, **kwargs)

    @override
    def model_dump_json(
        self,
        *,
        indent: int | None = None,
        **kwargs: Unpack[ModelDumpKwargs],
    ) -> str:
        kwargs = {**MODEL_DUMP_DEFAULTS, **kwargs}
        return super().model_dump_json(indent=indent, **kwargs)


# Base class with extra customization for GQL generated types.
# Omitted from docstring to avoid inclusion in generated docs.
class GQLBase(Base):
    model_config = ConfigDict(
        extra="ignore",
        protected_namespaces=(),
    )


# ------------------------------------------------------------------------------
# Reusable annotations for field types
T = TypeVar("T")

GQLId = Annotated[
    str,
    Field(repr=False, strict=True, frozen=True),
]

Typename = Annotated[
    T,
    Field(repr=False, alias="__typename", frozen=True),
]


# FIXME: Restore, modify, or replace this later after ensuring pydantic v1 compatibility.
# def validate_maybe_json(v: Any, handler: ValidatorFunctionWrapHandler) -> Any:
#     """Wraps default Json[...] field validator to allow instantiation with an already-decoded value."""
#     try:
#         return handler(v)
#     except ValidationError:
#         # Try revalidating after properly jsonifying the value
#         return handler(to_json(v, by_alias=True, round_trip=True))
#
#
# SerializedToJson = Annotated[
#     Json[T],
#     # Allow lenient instantiation/validation: incoming data may already be deserialized.
#     WrapValidator(validate_maybe_json),
# ]

SerializedToJson = Json[T]
