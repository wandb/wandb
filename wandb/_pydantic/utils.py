"""Internal utilities for working with Pydantic types and data."""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING, Any

import pydantic_core

if TYPE_CHECKING:
    from pydantic import BaseModel


@lru_cache
def gql_typename(cls: type[BaseModel]) -> str:
    """Get the GraphQL typename for a Pydantic model."""
    if (field := cls.model_fields.get("typename__")) and (typename := field.default):
        return typename
    raise TypeError(f"Cannot extract GraphQL typename from: {cls.__qualname__!r}.")


def from_json(s: str | bytes) -> Any:
    """Quickly deserialize a JSON string to a Python object."""
    return pydantic_core.from_json(s)


def to_json(v: Any) -> str:
    """Quickly serialize a (possibly Pydantic) object to a JSON string."""
    return pydantic_core.to_json(v, by_alias=True, round_trip=True).decode("utf-8")


def pydantic_isinstance(
    v: Any, classinfo: type[BaseModel] | tuple[type[BaseModel], ...]
) -> bool:
    """Return True if the object could be parsed into the given Pydantic type."""
    if isinstance(classinfo, tuple):
        return any(cls.__pydantic_validator__.isinstance_python(v) for cls in classinfo)
    cls = classinfo
    return cls.__pydantic_validator__.isinstance_python(v)
