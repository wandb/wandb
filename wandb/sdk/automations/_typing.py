from __future__ import annotations

from typing import Any, TypeAlias

from pydantic import Base64Str, Field, Json
from typing_extensions import Annotated, TypeVar

IntId = Annotated[int, Field(repr=False)]
Base64Id = Annotated[Base64Str, Field(repr=False)]
JsonDict: TypeAlias = Json[dict[str, Any]]

IntId: TypeAlias = int
UserId: TypeAlias = int
Base64Id: TypeAlias = Base64Str

NameT = TypeVar("NameT", bound=str)

TypenameField = Annotated[
    NameT,
    Field(repr=False, alias="__typename", frozen=True),
]
