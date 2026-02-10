"""Internal utilities for working with pydantic."""

__all__ = [
    "JsonableModel",
    "GQLBase",
    "GQLInput",
    "GQLResult",
    "Connection",
    "ConnectionWithTotal",
    "Edge",
    "PageInfo",
    "Typename",
    "GQLId",
    "pydantic_isinstance",
    "to_json",
    "from_json",
    "gql_typename",
    "ValidationError",
]

# Available in all supported Pydantic versions.
from pydantic import ValidationError

from .base import GQLBase, GQLInput, GQLResult, JsonableModel
from .field_types import GQLId, Typename
from .pagination import Connection, ConnectionWithTotal, Edge, PageInfo
from .utils import from_json, gql_typename, pydantic_isinstance, to_json
