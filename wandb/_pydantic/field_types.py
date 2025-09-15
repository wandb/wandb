"""Reusable field types and annotations for pydantic fields."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

from pydantic import Field, StrictStr
from typing_extensions import Annotated

from .utils import IS_PYDANTIC_V2

T = TypeVar("T")


#: GraphQL `__typename` fields
Typename = Annotated[T, Field(repr=False, frozen=True, alias="__typename")]


if IS_PYDANTIC_V2 or TYPE_CHECKING:
    GQLId = Annotated[StrictStr, Field(repr=False, frozen=True)]

else:
    # FIXME: Find a way to fix this for pydantic v1, which doesn't like when
    # `Field(...)` used in the field assignment AND `Annotated[...]`.
    # This is a problem for codegen, which can currently output e.g.
    #
    #   class MyModel(GQLBase):
    #       my_id: GQLId = Field(alias="myID")
    GQLId = StrictStr  # type: ignore[misc]
