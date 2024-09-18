from __future__ import annotations

from typing import Any, LiteralString, TypeAlias

from pydantic import Base64Str, Field, Json
from typing_extensions import Annotated, TypeVar

IntId = Annotated[int, Field()]

# Base64Id = Annotated[Base64Str, Field(repr=False)]
Base64Id = Annotated[str, Field(repr=False)]  # TODO: Fix this

JsonDict: TypeAlias = Json[dict[str, Any]]

IntId: TypeAlias = int
UserId: TypeAlias = int
Base64Id: TypeAlias = Base64Str

NameT = TypeVar("NameT", bound=LiteralString)

Typename = Annotated[
    NameT,
    Field(repr=False, alias="__typename", frozen=True),
]
