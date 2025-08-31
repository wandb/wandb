"""Reusable field types and annotations for pydantic fields."""

from __future__ import annotations

from typing import TypeVar

from pydantic import Field, StrictStr
from typing_extensions import Annotated

T = TypeVar("T")


#: GraphQL `__typename` fields
Typename = Annotated[T, Field(repr=False, frozen=True, alias="__typename")]
"""Annotates GraphQL `__typename` fields."""

GQLId = Annotated[StrictStr, Field(repr=False, frozen=True)]
"""Annotates GraphQL fields of scalar type `ID`."""
