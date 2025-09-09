"""Reusable field types and annotations for pydantic fields."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypeVar

from pydantic import Field, Json, StrictStr
from typing_extensions import Annotated

from .utils import IS_PYDANTIC_V2, to_json

T = TypeVar("T")


def ensure_json(v: Any) -> Any:
    """In case the incoming value isn't serialized JSON, reserialize it.

    This lets us use `Json[...]` fields with values that are already deserialized.
    """
    # NOTE: Assumes that the deserialized type is not itself a string.
    # Revisit this if we need to support deserialized types that are str/bytes.
    return v if isinstance(v, (str, bytes)) else to_json(v)


#: GraphQL `__typename` fields
Typename = Annotated[T, Field(repr=False, frozen=True, alias="__typename")]


if IS_PYDANTIC_V2 or TYPE_CHECKING:
    from pydantic import BeforeValidator, PlainSerializer

    GQLId = Annotated[StrictStr, Field(repr=False, frozen=True)]

    # Allow lenient instantiation/validation: incoming data may already be deserialized.
    SerializedToJson = Annotated[
        Json[T], BeforeValidator(ensure_json), PlainSerializer(to_json)
    ]

else:
    # FIXME: Find a way to fix this for pydantic v1, which doesn't like when
    # `Field(...)` used in the field assignment AND `Annotated[...]`.
    # This is a problem for codegen, which can currently output e.g.
    #
    #   class MyModel(GQLBase):
    #       my_id: GQLId = Field(alias="myID")
    GQLId = StrictStr  # type: ignore[misc]

    # FIXME: Restore, modify, or replace this later after ensuring pydantic v1 compatibility.
    SerializedToJson = Json[T]  # type: ignore[misc]
