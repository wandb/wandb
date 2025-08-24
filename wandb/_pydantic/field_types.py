"""Base classes and other customizations for generated pydantic types."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, TypeVar

from pydantic import Field, Json, StrictStr
from typing_extensions import Annotated, Self

from .utils import IS_PYDANTIC_V2, ensure_json, to_json

T = TypeVar("T")


#: GraphQL `__typename` fields
Typename = Annotated[T, Field(repr=False, frozen=True, alias="__typename")]


class Unset:
    """A falsey sentinel type to use as a placeholder value for unset fields.

    For internal use only.  Do not instantiate this class directly.  Instead,
    use the `UNSET` sentinel value.
    """

    _name: ClassVar[str] = "UNSET"

    def __bool__(self) -> bool:
        return False  # Ensure falsiness

    def __repr__(self) -> str:
        return f"<{self._name}>"

    def __reduce__(self) -> str:
        return self._name  # Ensure picklability

    def __copy__(self) -> Self:
        return self

    def __deepcopy__(self, _: Any) -> Self:
        return self


UNSET = Unset()


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
