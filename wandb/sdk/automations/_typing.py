from __future__ import annotations

from typing import LiteralString, TypeAlias, TypeVar

from pydantic import Field, Json, JsonValue
from typing_extensions import Annotated

Base64Id = Annotated[str, Field(repr=False, strict=True)]  # TODO: Fix this
JsonDict: TypeAlias = Json[dict[str, JsonValue]]

NameT = TypeVar("NameT", bound=LiteralString)

Typename = Annotated[
    NameT,
    Field(repr=False, alias="__typename", frozen=True),
]
T = TypeVar("T")
