"""Reusable field types and annotations for pydantic fields."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, TypeVar

from pydantic import Field, StrictStr

from .utils import IS_PYDANTIC_V2

T = TypeVar("T")

# HACK: Pydantic no longer seems to like it when you define a type alias
# at the module level with `Annotated[...]`.
# The commented TypeAliases are a hack to unblock CI for now.

# Typename = Annotated[T, Field(repr=False, frozen=True, alias="__typename")]
Typename = Annotated[T, Field(alias="__typename")]
"""Annotates GraphQL `__typename` fields."""


if IS_PYDANTIC_V2 or TYPE_CHECKING:
    # GQLId = Annotated[StrictStr, Field(repr=False, frozen=True)]
    GQLId = StrictStr

else:
    # FIXME: Find a way to fix this for pydantic v1, which doesn't like when
    # `Field(...)` used in the field assignment AND `Annotated[...]`.
    # This is a problem for codegen, which can currently output e.g.
    #
    #   class MyModel(GQLBase):
    #       my_id: GQLId = Field(alias="myID")
    GQLId = StrictStr  # type: ignore[misc]
