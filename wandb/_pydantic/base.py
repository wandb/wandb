"""Base classes and other customizations for generated pydantic types."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Iterator, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, Json
from typing_extensions import Annotated, TypedDict, Unpack, override

from .utils import to_json
from .v1_compat import IS_PYDANTIC_V2, PydanticCompatMixin

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


# v1-compatible base class for pydantic types.
class CompatBaseModel(PydanticCompatMixin, BaseModel):
    pass


# Base class for all generated classes/types.
# Omitted from docstring to avoid inclusion in generated docs.
class Base(CompatBaseModel):
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

if IS_PYDANTIC_V2:
    GQLId = Annotated[
        str,
        Field(repr=False, strict=True, frozen=True),
    ]
else:
    # FIXME: Find a way to fix this for pydantic v1, which doesn't like when
    # `Field(...)` used in the field assignment AND `Annotated[...]`.
    # This is a problem for codegen, which can currently outputs e.g.
    #
    #   class MyModel(GQLBase):
    #       my_id: GQLId = Field(alias="myID")
    #
    GQLId = str  # type: ignore[misc]

Typename = Annotated[
    T,
    Field(repr=False, alias="__typename", frozen=True),
]


if IS_PYDANTIC_V2:
    from pydantic import BeforeValidator

    def validate_maybe_json(v: Any) -> Any:
        """Wraps default Json[...] field validator to allow instantiation with an already-decoded value."""
        # NOTE: Assumes that the deserialized type is not itself a string.
        # Revisit this if we need to support deserialized types that are str/bytes.
        return v if isinstance(v, (str, bytes)) else to_json(v)

    SerializedToJson = Annotated[
        Json[T],
        # Allow lenient instantiation/validation: incoming data may already be deserialized.
        BeforeValidator(validate_maybe_json),
    ]
else:
    # TODO: Fix this for pydantic v1.
    # SerializedToJson = Json  # type: ignore[misc]

    class SerializedToJson(Json):  # type: ignore[no-redef]
        @classmethod
        def __get_validators__(cls) -> Iterator[Callable[[Any], Any]]:
            yield cls.validate

        @classmethod
        def validate(cls, v: Any) -> Any:
            return v if isinstance(v, (str, bytes)) else to_json(v)
