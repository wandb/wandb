"""Base classes and other customizations for generated pydantic types."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, Json, StrictStr
from typing_extensions import Annotated, TypedDict, Unpack, override

from .utils import IS_PYDANTIC_V2, to_json
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


# v1-compatible base class for pydantic types.
class CompatBaseModel(PydanticCompatMixin, BaseModel):
    __doc__ = None  # Prevent subclasses from inheriting the BaseModel docstring


# Base class for all GraphQL-generated types.
# Omitted from docstring to avoid inclusion in generated docs.
class GQLBase(CompatBaseModel):
    model_config = ConfigDict(
        populate_by_name=True,  # Discouraged in pydantic v2.11+, will be deprecated in v3
        validate_by_name=True,  # Introduced in pydantic v2.11
        validate_by_alias=True,  # Introduced in pydantic v2.11
        serialize_by_alias=True,  # Introduced in pydantic v2.11
        validate_assignment=True,
        validate_default=True,
        use_attribute_docstrings=True,
        from_attributes=True,
        revalidate_instances="always",
        protected_namespaces=(),  # Some GraphQL fields may begin with "model_"
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


# ------------------------------------------------------------------------------
# Reusable annotations for field types
T = TypeVar("T")

if IS_PYDANTIC_V2 or TYPE_CHECKING:
    GQLId = Annotated[
        StrictStr,
        Field(repr=False, frozen=True),
    ]
else:
    # FIXME: Find a way to fix this for pydantic v1, which doesn't like when
    # `Field(...)` used in the field assignment AND `Annotated[...]`.
    # This is a problem for codegen, which can currently outputs e.g.
    #
    #   class MyModel(GQLBase):
    #       my_id: GQLId = Field(alias="myID")
    #
    GQLId = StrictStr  # type: ignore[misc]

Typename = Annotated[
    T,
    Field(repr=False, frozen=True, alias="__typename"),
]


def ensure_json(v: Any) -> Any:
    """In case the incoming value isn't serialized JSON, reserialize it.

    This lets us use `Json[...]` fields with values that are already deserialized.
    """
    # NOTE: Assumes that the deserialized type is not itself a string.
    # Revisit this if we need to support deserialized types that are str/bytes.
    return v if isinstance(v, (str, bytes)) else to_json(v)


if IS_PYDANTIC_V2 or TYPE_CHECKING:
    from pydantic import BeforeValidator, PlainSerializer

    SerializedToJson = Annotated[
        Json[T],
        # Allow lenient instantiation/validation: incoming data may already be deserialized.
        BeforeValidator(ensure_json),
        PlainSerializer(to_json),
    ]
else:
    # FIXME: Restore, modify, or replace this later after ensuring pydantic v1 compatibility.
    SerializedToJson = Json[T]  # type: ignore[misc]
